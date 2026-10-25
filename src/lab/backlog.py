"""Backlog de hipótesis: `research/backlog.yaml` es la fuente única.

La nota del vault se genera desde el YAML (nunca al revés) y el panel lee el mismo archivo, así que
Obsidian y la pestaña Investigación no pueden diferir.

    python -m lab.backlog check                  valida el esquema
    python -m lab.backlog render --out NOTA.md   escribe la nota de Obsidian
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'research' / 'backlog.yaml'
TIPOS = {'costo': 'Costo', 'señal': 'Señal', 'externo': 'Externo', 'infra': 'Infra', 'otro': 'Otro'}
HIPOTESIS_CAMPOS = ('id', 'orden', 'tipo', 'titulo', 'idea', 'evidencia', 'prueba', 'estado')
BITACORA_CAMPOS = ('sprint', 'fecha', 'hipotesis', 'resultado', 'decision')
DESCARTADA_CAMPOS = ('idea', 'motivo', 'fuente')
INDICE = '[[Projects/Trading Lab/📈 Trading Lab — Índice|📈 Trading Lab]]'
TITULO = '🧪 Backlog de hipótesis — Trading Lab'
AVISO = 'Generada desde `trading-lab/research/backlog.yaml`; no la edites a mano.'


class BacklogError(ValueError):
    pass


def _text(value) -> str:
    return '' if value is None else str(value).strip()


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or data.get('version') != 1:
        raise BacklogError('Backlog sin versión 1')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', _text(data.get('actualizado'))):
        raise BacklogError('actualizado debe ser AAAA-MM-DD')
    items = data.get('hipotesis')
    if not isinstance(items, list) or not items:
        raise BacklogError('Faltan hipótesis')
    seen, orders = set(), set()
    for item in items:
        missing = [k for k in HIPOTESIS_CAMPOS if not _text(item.get(k))]
        if missing:
            raise BacklogError(f'Hipótesis {item.get("id")!r} sin {", ".join(missing)}')
        if item['id'] in seen:
            raise BacklogError(f'Id duplicado: {item["id"]}')
        if item['tipo'] not in TIPOS:
            raise BacklogError(f'Tipo desconocido en {item["id"]}: {item["tipo"]}')
        if not isinstance(item['orden'], int) or item['orden'] in orders:
            raise BacklogError(f'Orden inválido o repetido en {item["id"]}')
        seen.add(item['id'])
        orders.add(item['orden'])
    for item in data.get('descartadas') or []:
        if any(not _text(item.get(k)) for k in DESCARTADA_CAMPOS):
            raise BacklogError(f'Descartada incompleta: {item.get("idea")!r}')
        if item.get('id') in seen:
            raise BacklogError(f'Id duplicado entre pendientes y descartadas: {item["id"]}')
    for row in data.get('bitacora') or []:
        if any(not _text(row.get(k)) for k in BITACORA_CAMPOS):
            raise BacklogError(f'Fila de bitácora incompleta: {row.get("fecha")!r}')
    return data


def load(path: Path = PATH) -> dict:
    return validate(yaml.safe_load(Path(path).read_text(encoding='utf-8')))


def _cell(value) -> str:
    return ' '.join(_text(value).split()).replace('|', '\\|')


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    lines += ['| ' + ' | '.join(_cell(c) for c in row) + ' |' for row in rows]
    return lines


def ordered(data: dict) -> list[dict]:
    return sorted(data['hipotesis'], key=lambda h: h['orden'])


def render_note(data: dict) -> str:
    data = validate(data)
    note = data.get('nota') or {}
    tags = ', '.join(note.get('tags') or [])
    out = ['---', f'fecha: {data["actualizado"]}', f'tags: [{tags}]', f'estado: {note.get("estado", "activo")}',
           '---', '', f'# {TITULO}', '', f'↩︎ {INDICE}', '', f'> {AVISO}', '']
    if _text(data.get('intro')):
        out += [_text(data['intro']), '']
    if _text(data.get('barras')):
        out += [_text(data['barras']), '']
    if _text(data.get('por_que_el_orden')):
        out += ['## Por qué el orden', '', _text(data['por_que_el_orden']), '']
    out += ['## Pendientes', '']
    out += _table(['#', 'Tipo', 'Hipótesis', 'Evidencia previa', 'Prueba mínima', 'Estado'],
                  [[h['id'], TIPOS[h['tipo']], h['idea'], h['evidencia'], h['prueba'], h['estado']]
                   for h in ordered(data)])
    out += ['', '## Descartadas (no repetir sin dato nuevo)', '']
    out += _table(['Idea', 'Motivo', 'Fuente'], [[d['idea'], d['motivo'], d['fuente']]
                                                 for d in data.get('descartadas') or []])
    out += ['', '## Bitácora de sprints', '']
    out += _table(['Fecha', 'Hipótesis', 'Resultado', 'Decisión'],
                  [[r['fecha'], f'Sprint {r["sprint"]}: {_text(r["hipotesis"])}', r['resultado'], r['decision']]
                   for r in data.get('bitacora') or []])
    return '\n'.join(out) + '\n'


def summary(data: dict) -> dict:
    """Lo que muestra la pestaña Investigación del panel."""
    data = validate(data)
    pending = [{'id': h['id'], 'orden': h['orden'], 'tipo': h['tipo'], 'titulo': h['titulo'], 'idea': _cell(h['idea']),
                'estado': _cell(h['estado']), 'pausada': bool(h.get('pausada'))} for h in ordered(data)]
    nxt = next((h for h in pending if not h['pausada']), None)
    log = [{'sprint': _text(r['sprint']), 'fecha': _text(r['fecha']), 'hipotesis': _cell(r['hipotesis']),
            'resultado': _cell(r['resultado']), 'decision': _cell(r['decision']), 'enlace': _text(r.get('enlace')) or None}
           for r in data.get('bitacora') or []]
    gone = [{'id': d.get('id'), 'idea': _cell(d['idea']), 'motivo': _cell(d['motivo']), 'fuente': _cell(d['fuente'])}
            for d in data.get('descartadas') or []]
    return {'actualizado': _text(data['actualizado']), 'hipotesis': pending, 'siguiente': nxt,
            'descartadas': gone, 'bitacora': log}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['check', 'render'])
    parser.add_argument('--file', type=Path, default=PATH)
    parser.add_argument('--out', type=Path, help='nota de Obsidian a escribir (render); sin --out imprime')
    args = parser.parse_args(argv)
    try:
        data = load(args.file)
    except (BacklogError, yaml.YAMLError) as exc:
        print(f'Backlog inválido: {exc}', file=sys.stderr)
        return 1
    if args.action == 'check':
        s = summary(data)
        print(f'OK: {len(s["hipotesis"])} pendientes, {len(s["descartadas"])} descartadas, '
              f'{len(s["bitacora"])} sprints; siguiente {s["siguiente"]["id"] if s["siguiente"] else "ninguna"}')
        return 0
    text = render_note(data)
    if args.out:
        args.out.write_text(text, encoding='utf-8')
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
