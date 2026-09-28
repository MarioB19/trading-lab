"""Order journal and sleeve ownership for external brokers.

Only quantities acquired by this ledger belong to the sleeve. Existing balances
are never adopted. Unknown submissions are reconciled, never blindly resent.
"""
from __future__ import annotations

import hashlib
import copy
import json
from dataclasses import replace
from datetime import datetime, timezone

from .brokers import Fill
from .storage import utcnow


class JournalBroker:
    manages_ledger = True

    def __init__(self, broker, store, sleeve, mode, sc, state):
        self.broker, self.store, self.st = broker, store, state
        self.sleeve, self.mode, self.sc = sleeve, mode, sc
        self.name, self.min_order_value = broker.name, broker.min_order_value
        account = getattr(broker, 'account_key', broker.name)
        self.account_prefix = 'ledger:' + account + ':'
        self.namespace = self.account_prefix + mode + ':' + sleeve
        self.candle = ''
        if state.get('account_namespace') not in (None, self.namespace):
            raise RuntimeError('la identidad de cuenta cambió; requiere migración explícita')
        with store.transaction() as db:
            ledger = store._read(db, self.namespace)
            if ledger is None:
                if state.get('last_candle') and ('sleeve_cash' in state or state.get('ledger')):
                    raise RuntimeError('cambio de broker o estado externo legacy: requiere migración explícita de propiedad')
                other = db.execute('SELECT payload FROM documents WHERE substr(name,1,?)=?',
                                   (len(self.account_prefix), self.account_prefix)).fetchall()
                allocated = sum(max(0, float(json.loads(row[0])['cash'])) for row in other)
                available = max(0, float(broker.cash()) - allocated)
                ledger = {'cash': min(float(sc['capital']), available), 'positions': {}, 'capital_base': float(sc['capital']),
                          'created_at': utcnow()}
                store._write(db, self.namespace, ledger)
        self._sync()

    def _sync(self):
        ledger = self.store.read_document(self.namespace)
        self.st['sleeve_cash'] = ledger['cash']
        self.st['owned_positions'] = dict(ledger['positions'])
        self.st['capital_base'] = ledger['capital_base']
        self.st['account_namespace'] = self.namespace
        return ledger

    def _checkpoint(self, db, ledger=None):
        state = self.store._read(db, 'state', {'sleeves': {}})
        current = copy.deepcopy(self.st)
        if ledger is not None:
            current.update(sleeve_cash=ledger['cash'], owned_positions=dict(ledger['positions']),
                           capital_base=ledger['capital_base'], account_namespace=self.namespace)
        current['execution_pending'] = True
        state.setdefault('sleeves', {})[self.sleeve] = current
        self.store._write(db, 'state', state)

    def checkpoint_risk(self):
        with self.store.transaction() as db:
            self._checkpoint(db, self.store._read(db, self.namespace))

    def adjust_capital(self, delta):
        # A durable cash adjustment without its equity-flow and risk checkpoint
        # is unsafe across a crash. The initial paper pilot deliberately requires
        # an explicit, reconciled migration for external allocation changes.
        raise RuntimeError("cambio de capital en cuenta externa requiere migración explícita conciliada; no se modifica el ledger")

    def positions(self):
        ledger = self._sync()
        actual = self.broker.positions()
        # Account-wide ownership check: another sleeve cannot mask missing holdings.
        with self.store.connect() as db:
            rows = db.execute('SELECT payload FROM documents WHERE substr(name,1,?)=?',
                              (len(self.account_prefix), self.account_prefix)).fetchall()
        import json
        total = {}
        for row in rows:
            for asset, qty in json.loads(row[0])['positions'].items():
                total[asset] = total.get(asset, 0) + qty
        for asset, qty in total.items():
            if float(actual.get(asset, 0)) + max(1e-8, qty * 1e-6) < qty:
                raise RuntimeError(f'{asset}: saldo del broker menor que propiedad registrada; conciliación requerida')
        return {a: q for a, q in ledger['positions'].items() if q > 1e-10}

    def cash(self):
        # Reserved cash still belongs to the sleeve until a fill. Valuing only
        # broker.free would manufacture losses while limit orders remain open.
        ledger = self._sync()
        with self.store.connect() as db:
            rows = db.execute('SELECT payload FROM documents WHERE substr(name,1,?)=?',
                              (len(self.account_prefix), self.account_prefix)).fetchall()
        allocated = sum(max(0, float(json.loads(row[0])['cash'])) for row in rows)
        reserved = sum(max(0, o.get('max_notional', o['qty'] * o['ref']) - o.get('filled_cost', 0)) * 1.01
                       for o in self.store.orders(pending_only=True)
                       if o['namespace'].startswith(self.account_prefix) and o['side'] == 'buy')
        if float(self.broker.cash()) + reserved + .01 < allocated:
            raise RuntimeError('efectivo externo menor que asignación registrada; conciliación requerida')
        return float(ledger['cash'])

    def available_cash(self):
        return min(float(self.broker.cash()), float(self._sync()['cash']))

    def asset_info(self, symbol):
        fn = getattr(self.broker, 'asset_info', None)
        return fn(symbol) if fn else {'tradable': True, 'fractionable': True}

    def pending(self):
        pending = self.store.orders(self.namespace, pending_only=True)
        if pending:
            return len(pending)
        # Also fail closed on orders not belonging to this process/account journal.
        return self.broker.pending()

    def _apply(self, order, fill):
        """Cumulative broker fill -> one atomic incremental accounting entry."""
        with self.store.transaction() as db:
            import json
            saved = db.execute('SELECT payload FROM orders WHERE id=?', (order['id'],)).fetchone()
            order = json.loads(saved[0])
            before = float(order.get('filled_qty', 0))
            old_cost, old_fee = float(order.get('filled_cost', 0)), float(order.get('filled_fee', 0))
            cumulative_qty = float(fill.qty)
            # Unknown responses carry no authoritative fill total; preserve prior fills.
            if fill.status == 'unknown':
                cumulative_qty, cumulative_cost, cumulative_fee = before, old_cost, old_fee
            else:
                cumulative_cost, cumulative_fee = cumulative_qty * fill.price, float(fill.fee)
            delta = cumulative_qty - before
            if delta < -1e-8 or cumulative_cost < old_cost - 1e-6 or cumulative_fee < old_fee - 1e-6:
                raise RuntimeError('respuesta de broker retrocede fills; conciliación requerida')
            cost, fee = cumulative_cost - old_cost, cumulative_fee - old_fee
            ledger = self.store._read(db, self.namespace)
            execution_id = ''
            if delta > 1e-10 or abs(cost) > 1e-8 or abs(fee) > 1e-8:
                asset, side = order['asset'], order['side']
                own = float(ledger['positions'].get(asset, 0))
                if side == 'sell' and delta > own + 1e-8:
                    raise RuntimeError('fill de venta excede propiedad del bloque')
                ledger['positions'][asset] = max(0, own + (delta if side == 'buy' else -delta))
                ledger['cash'] += -cost - fee if side == 'buy' else cost - fee
                self.store._write(db, self.namespace, ledger)
                execution_id = order['id'] + ':' + hashlib.sha256(f'{cumulative_qty}:{cumulative_cost}:{cumulative_fee}'.encode()).hexdigest()[:16]
                price = cost / delta if delta > 1e-10 else fill.price
                row = {'run_at_utc': utcnow(), 'sleeve': self.sleeve, 'mode': self.mode, 'broker': self.name,
                       'candle': order['candle'], 'asset': asset, 'side': side, 'qty': delta, 'price': price,
                       'value': cost, 'fee': fee, 'status': 'filled' if fill.terminal else 'partial',
                       'note': 'fill conciliado', 'ref_price': order['ref'],
                       'cost_bps': (((price / order['ref'] - 1) * (1 if side == 'buy' else -1) + fee / cost) * 10000
                                    if order['ref'] > 0 and cost > 0 and delta > 0 else ''),
                       'order_id': fill.order_id or order.get('broker_id', ''), 'execution_id': execution_id}
                self.store._rows(db, 'trades', [row])
            order.update(status=fill.status, terminal=fill.terminal, filled_qty=cumulative_qty,
                         filled_cost=cumulative_cost, filled_fee=cumulative_fee, updated_at=utcnow(),
                         broker_id=fill.order_id or order.get('broker_id', ''), note=fill.note)
            self.store.put_order(db, order)
            self._checkpoint(db, ledger)
        self._sync()
        return replace(fill, qty=max(0, delta), price=cost / delta if delta > 1e-10 else fill.price,
                       fee=fee, execution_id=execution_id)

    def reconcile(self):
        for order in self.store.orders(self.namespace, pending_only=True):
            try:
                fill = self.broker.lookup_order(order)
            except Exception as exc:
                fill = Fill(order['asset'], order['side'], 0, order['ref'], 0, 'unknown',
                            'conciliación pendiente: ' + type(exc).__name__, order['ref'],
                            order_id=order.get('broker_id', ''), client_order_id=order['id'], terminal=False)
            self._apply(order, fill)
        self._sync()
        return self.pending()

    def execute(self, asset, side, qty, ref_price):
        if self.pending():
            raise RuntimeError('existen órdenes sin resolver; no se envía otra orden')
        if side == 'sell':
            qty = min(qty, self.positions().get(asset, 0))
        elif qty * ref_price > self.available_cash() + 1e-8:
            return Fill(asset, side, 0, ref_price, 0, 'failed', 'efectivo disponible insuficiente')
        if qty <= 0:
            return Fill(asset, side, 0, ref_price, 0, 'failed', 'sin propiedad para operar')
        history = [o for o in self.store.orders(self.namespace) if o['candle'] == self.candle
                   and o['asset'] == asset and o['side'] == side]
        if history and history[-1]['status'] == 'failed':
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(history[-1]['updated_at'])).total_seconds()
            if age < 60:
                return Fill(asset, side, 0, ref_price, 0, 'failed', 'reintento con espera mínima de 60 segundos')
        identity = f'{self.namespace}:{self.candle}:{asset}:{side}:{len(history)}'
        order = {'id': 'tl-' + hashlib.sha256(identity.encode()).hexdigest()[:32],
                 'namespace': self.namespace, 'candle': self.candle, 'asset': asset, 'side': side,
                 'qty': qty, 'ref': ref_price, 'max_notional': qty * ref_price,
                 'status': 'intent', 'terminal': False,
                 'filled_qty': 0, 'filled_cost': 0, 'filled_fee': 0, 'broker_id': '', 'updated_at': utcnow()}
        with self.store.transaction() as db:
            if db.execute('SELECT 1 FROM orders WHERE namespace=? AND terminal=0', (self.namespace,)).fetchone():
                raise RuntimeError('una intención pendiente impide otra ejecución')
            self.store.put_order(db, order)
            self._checkpoint(db)
        try:
            kwargs = {'client_order_id': order['id']}
            if getattr(self.broker, 'supports_cash_budget', False) and side == 'buy':
                kwargs['max_notional'] = qty * ref_price
            fill = self.broker.execute(asset, side, qty, ref_price, **kwargs)
        except Exception as exc:
            fill = Fill(asset, side, 0, ref_price, 0, 'unknown', type(exc).__name__, ref_price,
                        client_order_id=order['id'], terminal=False)
        return self._apply(order, fill)
