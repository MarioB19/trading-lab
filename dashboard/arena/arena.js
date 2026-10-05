'use strict';
const names=['Day trading / scalping','Swing / tendencias','Reversión a la media','Creación de mercado'];
const short=['Scalping','Swing','Reversión','Market making'];
const ids=['scalping-v1','swing-v1','mean-reversion-v1','market-making-v1'];
const colors=['#198365','#437fd0','#8b66c7','#bf8934'];
const horizons=['Velas de 5 minutos','Cierre diario','Velas de 1 hora','Libro de órdenes · cada 15 s'];
let data=null,range='all',tab='trades',filter='all',busy=false;
const $=id=>document.getElementById(id);
const money=n=>new Intl.NumberFormat('es-MX',{style:'currency',currency:'USD',minimumFractionDigits:2}).format(n);
const pct=n=>`${n>=0?'+':''}${(n*100).toFixed(2)}%`;
const signed=n=>`${n>=0?'+':'−'}${money(Math.abs(n))}`;
const tone=n=>Math.abs(n)<.005?'neutral':n>0?'positive':'negative';
const date=n=>new Intl.DateTimeFormat('es-MX',{month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'America/Mexico_City'}).format(n);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function empty(title,detail){return `<div class="empty"><span class="empty-icon" aria-hidden="true">⌁</span><strong>${esc(title)}</strong><span>${esc(detail)}</span></div>`;}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,5000);}
function render(){
 const total=data.total_equity,pnl=total-4000;
 $('total').textContent=money(total);$('pnl').textContent=signed(pnl);$('pnl').className=tone(pnl);$('return').textContent=`${pct(pnl/4000)} · después de comisiones`;
 $('fees').textContent=money(data.wallets.reduce((s,w)=>s+w.fees,0));
 const start=data.manifest.started_at?Date.parse(data.manifest.started_at):null;
 $('days').textContent=start?`${Math.max(0,Math.floor((data.last_observed_ms-start)/86400000))} / 28 días`:'Sin iniciar';
 $('updated').textContent=data.last_observed_ms?`Último dato: ${date(data.last_observed_ms)} CDMX`:'Pendiente del primer ciclo';
 let notice='Simulación en marcha. Cada cartera opera con su propio efectivo e inventario.';
 $('notice').className='notice';
 if(data.kind==='synthetic'){notice='DEMOSTRACIÓN ARTIFICIAL · Estas cifras prueban la interfaz y el motor; no son resultados de mercado.';$('notice').classList.add('demo');}
 else if(!data.execution_authorized){notice='Carteras preparadas · US$1,000 ficticios por estrategia. La simulación espera el preregistro aprobado y la versión congelada.';}
 else if(data.stale){notice='La captura de mercado no está actualizada. Se conserva la última valoración; verifica el proceso de simulación.';$('notice').classList.add('error');}
 if(data.health.status==='error'){notice=`Captura detenida: ${data.health.error}. No se inventan precios ni operaciones.`;$('notice').classList.add('error');}
 $('notice').textContent=notice;
 $('cards').innerHTML=data.wallets.map((w,i)=>{
  const state=w.risk_stopped?'Freno de riesgo':w.paused?'En pausa':!data.execution_authorized&&data.kind!=='synthetic'?'Preparada':data.stale?'Sin dato fresco':w.status==='running'?'Observando':'En espera';
  return `<article class="card strategy-${i}"><div class="card-top"><span class="card-num">0${i+1}</span><span class="state">${state}</span></div><h3>${names[i]}</h3><span class="horizon">${horizons[i]}</span><div class="balance">${money(w.equity)}</div><div class="card-result ${tone(w.equity-1000)}">${signed(w.equity-1000)} &nbsp;·&nbsp; ${pct((w.equity-1000)/1000)}</div><div class="metrics"><div><span>Efectivo</span><b>${money(w.cash)}</b></div><div><span>Inventario BTC</span><b>${money(w.qty*(w.mark||0))}</b></div><div><span>Comisiones</span><b>${money(w.fees)}</b></div><div><span>Caída desde máximo</span><b>${(w.drawdown*100).toFixed(2)}%</b></div><div><span>Resultado realizado</span><b class="${tone(w.realized)}">${signed(w.realized)}</b></div><div><span>Posición abierta</span><b class="${tone(w.unrealized||0)}">${signed(w.unrealized||0)}</b></div></div><p class="reason">${esc(w.reason)}</p><div class="card-actions"><button class="button" data-detail="${w.id}">Ver actividad (${w.fills})</button><button class="button" data-control="${w.id}" data-action="${w.paused?'resume':'pause'}" ${w.risk_stopped?'disabled':''}>${w.paused?'Reanudar':'Pausar'}</button></div></article>`;
 }).join('');
 $('legend').innerHTML=short.map((n,i)=>`<span class="strategy-${i}"><i class="dot"></i>${n}</span>`).join('');
 renderChart();renderActivity();
}
function renderChart(){
 const after=range==='day'?(data.last_observed_ms||0)-86400000:range==='week'?(data.last_observed_ms||0)-7*86400000:0;
 const series=ids.map(id=>(data.history[id]||[]).filter(p=>p.ts>=after));
 const points=series.flat();
 if(points.length<8){$('chart').innerHTML=empty('El experimento empieza desde aquí','La gráfica aparecerá cuando existan al menos dos observaciones por cartera.');return;}
 const width=1000,height=245,left=68,right=15,top=15,bottom=34;
 let min=Math.min(1000,...points.map(p=>p.equity)),max=Math.max(1000,...points.map(p=>p.equity));
 const padding=Math.max(.5,(max-min)*.15);min-=padding;max+=padding;
 const t0=Math.min(...points.map(p=>p.ts)),t1=Math.max(...points.map(p=>p.ts));
 const x=t=>left+(t-t0)/Math.max(1,t1-t0)*(width-left-right),y=v=>top+(max-v)/(max-min)*(height-top-bottom);
 let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Patrimonio en dólares de las cuatro carteras a lo largo de las observaciones">`;
 for(let i=0;i<5;i++){const value=min+(max-min)*i/4,yy=y(value);svg+=`<line x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}" stroke="#edf1f0"/><text x="${left-12}" y="${yy+4}" text-anchor="end" fill="#7c8a91" font-size="11">${money(value)}</text>`;}
 svg+=`<line x1="${left}" x2="${width-right}" y1="${y(1000)}" y2="${y(1000)}" stroke="#aebcb6" stroke-dasharray="4 5"/>`;
 series.forEach((values,i)=>{const path=values.map((p,j)=>`${j?'L':'M'}${x(p.ts).toFixed(2)},${y(p.equity).toFixed(2)}`).join(' ');svg+=`<path d="${path}" fill="none" stroke="${colors[i]}" stroke-width="2"/>`;if(values.length){const p=values[values.length-1];svg+=`<circle cx="${x(p.ts)}" cy="${y(p.equity)}" r="3" fill="${colors[i]}"><title>${esc(names[i])}: ${money(p.equity)}</title></circle>`;}});
 svg+=`<text x="${left}" y="${height-7}" fill="#7c8a91" font-size="10">${esc(date(t0))}</text><text x="${width-right}" y="${height-7}" text-anchor="end" fill="#7c8a91" font-size="10">${esc(date(t1))} CDMX</text></svg>`;
 $('chart').innerHTML=svg;
 $('chart-caption').textContent=`${data.counts.captures} capturas · línea discontinua: capital inicial. ${data.benchmark_equity?`Referencia BTC: ${money(data.benchmark_equity)} por US$1,000 (compra estimada).`:''}`;
}
function table(head,rows){return `<table><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`;}
function renderActivity(){
 let rows=[];
 if(tab==='trades'){
  rows=data.fills.filter(f=>filter==='all'||f.strategy===filter).map(f=>[esc(date(f.ts)),short[ids.indexOf(f.strategy)],`<span class="side ${f.side}">${f.side==='buy'?'Compra':'Venta'}</span>`,f.qty.toFixed(8),money(f.price),money(f.value),money(f.fee),esc(f.liquidity)]);
  $('activity-content').innerHTML=rows.length?table(['Fecha · CDMX','Cartera','Operación','BTC','Precio','Importe','Comisión','Ejecución'],rows):empty('Todavía no hay operaciones','El motor espera las condiciones de cada estrategia. No operar también es una decisión.');
 }else if(tab==='decisions'){
  rows=data.decisions.filter(f=>filter==='all'||f.strategy===filter).map(f=>[esc(date(f.ts)),short[ids.indexOf(f.strategy)],esc(f.reason)]);
  $('activity-content').innerHTML=rows.length?table(['Fecha · CDMX','Cartera','Decisión registrada'],rows):empty('Las decisiones aparecerán aquí','Se conserva la razón de cada cambio de señal o estado.');
 }else{
  data.wallets.filter(w=>filter==='all'||w.id===filter).forEach(w=>w.quotes.forEach(q=>rows.push([short[ids.indexOf(w.id)],q.side==='buy'?'Compra':'Venta',money(q.price),q.qty.toFixed(8),esc(date(q.expires_ms))])));
  $('activity-content').innerHTML=rows.length?table(['Cartera','Lado','Precio límite','BTC','Vence · CDMX'],rows):empty('Sin cotizaciones abiertas','Creación de mercado cotiza solo con efectivo e inventario disponibles.');
 }
}
async function refresh(){if(busy)return;busy=true;$('refresh').disabled=true;try{const response=await fetch('/api/arena');if(!response.ok)throw Error('No se pudo leer el estado');data=await response.json();render();}catch(error){$('notice').textContent='Sin conexión al proceso local. Los últimos datos visibles no se han actualizado.';$('notice').className='notice error';}finally{busy=false;$('refresh').disabled=false;}}
$('strategy-filter').innerHTML+=""+ids.map((id,i)=>`<option value="${id}">${names[i]}</option>`).join('');
$('strategy-filter').addEventListener('change',e=>{filter=e.target.value;renderActivity();});
$('refresh').addEventListener('click',refresh);
document.addEventListener('click',async event=>{
 const detail=event.target.closest('[data-detail]');if(detail){filter=detail.dataset.detail;$('strategy-filter').value=filter;renderActivity();$('activity').scrollIntoView({behavior:'smooth'});}
 const rb=event.target.closest('[data-range]');if(rb){range=rb.dataset.range;document.querySelectorAll('[data-range]').forEach(b=>b.classList.toggle('selected',b===rb));if(data)renderChart();}
 const tb=event.target.closest('[data-tab]');if(tb){tab=tb.dataset.tab;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b===tb));if(data)renderActivity();}
 const cb=event.target.closest('[data-control]');if(cb){cb.disabled=true;try{const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({strategy:cb.dataset.control,action:cb.dataset.action})});const result=await response.json();if(!response.ok)throw Error(result.error);data=result;render();toast(cb.dataset.action==='pause'?'Cartera pausada. El inventario se conserva.':'Cartera lista para el siguiente ciclo.');}catch(error){toast(error.message);cb.disabled=false;}}
});
refresh();setInterval(refresh,15000);
