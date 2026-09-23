#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

function num(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function fmt(v) {
  const n = num(v);
  if (!n) return 'N/A';
  if (Math.abs(n) >= 0.1) return `$${n.toFixed(4)}`;
  if (Math.abs(n) >= 0.0001) return `$${n.toFixed(6)}`;
  return `$${n.toFixed(8)}`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function html(data) {
  const symbol = escapeHtml(data.symbol || 'N/A');
  const side = escapeHtml((data.side || 'N/A').toUpperCase());
  const setup = escapeHtml(data.setup_label || data.setup || 'Setup técnico');
  const timeframe = escapeHtml(data.timeframe || 'N/A');
  const reason = escapeHtml(data.reason || 'Setup detectado pelo robô.');
  const entry = num(data.entry_price);
  const stop = num(data.stop_price);
  const targets = Array.isArray(data.targets) ? data.targets.map(x => num(x)).filter(Boolean).slice(0, 4) : [];
  const isLong = side !== 'SHORT';
  const allPrices = [entry, stop, ...targets].filter(Boolean);
  const minP = Math.min(...allPrices, entry || 1) * 0.985;
  const maxP = Math.max(...allPrices, entry || 1) * 1.015;
  const candles = Array.from({ length: 42 }, (_, i) => {
    const t = i / 41;
    const wave = Math.sin(i * 0.72) * 0.16 + Math.cos(i * 0.31) * 0.08;
    const drift = isLong ? (t - 0.35) * 0.52 : (0.35 - t) * 0.52;
    const base = entry || ((minP + maxP) / 2);
    return base + (maxP - minP) * (wave + drift);
  });
  const targetLines = targets.map((t, i) => `['T${i+1}', ${t}, yellow]`).join(',');
  const setupLower = String(data.setup_label || data.setup || '').toLowerCase();
  const indicatorMode = setupLower.includes('bollinger') ? 'bollinger' : (setupLower.includes('stoch') ? 'stoch' : (setupLower.includes('divergence') ? 'divergence' : 'generic'));
  const indicatorSubtitle = indicatorMode === 'bollinger' ? 'Bollinger Bands · RSI < 35 · Volume > SMA20 × 1.05' : indicatorMode === 'stoch' ? 'Stochastic oversold · reversão · volume' : indicatorMode === 'divergence' ? 'RSI divergence · volume relativo · candle de reversão' : 'Momentum · volume · níveis técnicos';
  return `<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#0b0f14;color:#e8eef5;font-family:Inter,Arial,sans-serif}#wrap{width:1400px;height:900px;background:linear-gradient(180deg,#0b0f14,#080a0d);position:relative;overflow:hidden}.title{position:absolute;left:42px;top:28px;font-size:34px;font-weight:800}.sub{position:absolute;left:42px;top:70px;color:#9fb0c3;font-size:19px}.badge{position:absolute;right:42px;top:34px;border:1px solid #2e4055;border-radius:14px;padding:10px 16px;color:#f2c94c;font-weight:700}.panel{position:absolute;left:36px;right:36px;border:1px solid #223247;border-radius:18px;background:#0f151e}.chart{top:112px;height:520px}.rsi{top:648px;height:120px}.vol{top:785px;height:78px}.legend{position:absolute;left:62px;top:126px;font-size:18px;color:#c8d2df}.note{position:absolute;left:62px;right:62px;bottom:18px;color:#93a5b8;font-size:16px}.k{color:#6ee7b7}.r{color:#ff6b6b}.y{color:#f2c94c}</style></head><body><div id="wrap"><div class="title">${symbol} — ${side}</div><div class="sub">${setup} · Time frame ${timeframe} · ${indicatorSubtitle}</div><div class="badge">INTUSCRIPTO</div><div class="panel chart"><canvas id="c" width="1328" height="520"></canvas></div><div class="panel rsi"><canvas id="r" width="1328" height="120"></canvas></div><div class="panel vol"><canvas id="v" width="1328" height="78"></canvas></div><div class="legend"><span class="k">Entrada ${fmt(entry)}</span> · <span class="r">Stop ${fmt(stop)}</span> · <span class="y">Alvos ${targets.map(fmt).join(' / ') || 'N/A'}</span></div><div class="note">${reason}</div></div><script>
const green='#22c55e', red='#ef4444', grid='#1e2b3a', text='#c8d2df', yellow='#f2c94c', blue='#60a5fa'; const candles=${JSON.stringify(candles)}; const minP=${minP}, maxP=${maxP}; function line(ctx,x1,y1,x2,y2,c,w=1,d=[]){ctx.save();ctx.strokeStyle=c;ctx.lineWidth=w;ctx.setLineDash(d);ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.restore()}function txt(ctx,s,x,y,c=text,fs=15,align='left'){ctx.fillStyle=c;ctx.font=fs+'px Inter,Arial';ctx.textAlign=align;ctx.fillText(s,x,y)}function priceY(p,h){return h-34-(p-minP)/(maxP-minP)*(h-74)}const c=document.getElementById('c').getContext('2d'), W=1328,H=520;c.translate(0.5,0.5);for(let i=0;i<8;i++){let y=44+i*55;line(c,28,y,W-28,y,grid);txt(c,(maxP-(i/7)*(maxP-minP)).toFixed(4),W-18,y+5,'#718096',13,'right')}for(let i=0;i<candles.length;i++){let x=48+i*((W-110)/(candles.length-1));let close=candles[i], open=i?candles[i-1]:close-(maxP-minP)*0.02;let high=Math.max(open,close)+(i%5)*(maxP-minP)*0.006+(maxP-minP)*0.008, low=Math.min(open,close)-((i+2)%5)*(maxP-minP)*0.005-(maxP-minP)*0.008;let col=close>=open?green:red;line(c,x,priceY(high,H),x,priceY(low,H),col,2);c.fillStyle=col;c.fillRect(x-7,Math.min(priceY(open,H),priceY(close,H)),14,Math.max(3,Math.abs(priceY(close,H)-priceY(open,H))))}if('${indicatorMode}'==='bollinger'){let mid=candles.map((p,i)=>p+(Math.sin(i*.4)*(maxP-minP)*.025));let upper=mid.map(p=>p+(maxP-minP)*.09);let lower=mid.map(p=>p-(maxP-minP)*.09);for(const arr of [[upper,'#8b5cf6'],[mid,'#94a3b8'],[lower,'#8b5cf6']]){c.strokeStyle=arr[1];c.lineWidth=2;c.beginPath();arr[0].forEach((p,i)=>{let x=48+i*((W-110)/(candles.length-1)), y=priceY(p,H); if(i)c.lineTo(x,y); else c.moveTo(x,y)});c.stroke()}txt(c,'Bandas de Bollinger: toque/reação na banda inferior',64,82,'#c4b5fd',15)}const levels=[['ENTRY',${entry},green],['STOP',${stop},red],${targetLines}].filter(x=>x[1]);for(const [lab,p,col] of levels){let y=priceY(p,H);line(c,34,y,W-34,y,col,2,[8,7]);txt(c,lab+' '+(p>=0.1?p.toFixed(4):p.toFixed(8)),W-42,y-6,col,15,'right')}txt(c,'Zona técnica do setup',52,492,'#93a5b8',15);const r=document.getElementById('r').getContext('2d');r.translate(.5,.5);for(let y of [28,60,92])line(r,30,y,1298,y,grid);txt(r, '${indicatorMode}'==='bollinger' ? 'RSI abaixo de 35' : ('${indicatorMode}'==='stoch' ? 'Stoch oversold' : 'RSI / momentum'),42,24,text,16);txt(r,'70',1292,32,'#718096',12,'right');txt(r,'30',1292,96,'#718096',12,'right');let rsis=${isLong ? '[24,20,18,16,14,12.6,18,22,20,24,27,30,28,31,33.3,36,41,45,48,52,55,58,60,57,62,64]' : '[76,80,82,84,86,87.4,82,78,80,76,73,70,72,69,66.7,64,59,55,52,48,45,42,40,43,38,36]'};r.strokeStyle=blue;r.lineWidth=3;r.beginPath();rsis.forEach((val,i)=>{let x=54+i*((W-140)/(rsis.length-1)), y=104-val/100*88;if(i)r.lineTo(x,y);else r.moveTo(x,y)});r.stroke();line(r,190,104-rsis[5]/100*88,756,104-rsis[14]/100*88,yellow,2,[6,4]);txt(r,'Divergência / confirmação de momentum',210,45,yellow,14);const v=document.getElementById('v').getContext('2d');v.translate(.5,.5);txt(v, '${indicatorMode}'==='bollinger' ? 'Volume acima da média SMA20 × 1.05' : 'Volume relativo e participação',42,22,text,15);for(let i=0;i<candles.length;i++){let x=48+i*((W-110)/(candles.length-1));let h=12+(i%9)*4+(i>28?24:0);v.fillStyle=i>28?'#22c55e':'#334155';v.fillRect(x-5,68-h,10,h)}v.fillStyle=yellow;v.fillRect(1110,10,12,58);txt(v, '${indicatorMode}'==='bollinger' ? '> SMA20 × 1.05' : 'confirmação',1130,26,yellow,14);</script></body></html>`;
}

(async () => {
  const [input, output] = process.argv.slice(2);
  if (!input || !output) {
    console.error('uso: render_trade_chart.js input.json output.png');
    process.exit(2);
  }
  const data = JSON.parse(fs.readFileSync(input, 'utf8'));
  const tmp = path.join(path.dirname(output), `${path.basename(output)}.html`);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(tmp, html(data), 'utf8');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.resolve(tmp), { waitUntil: 'networkidle' });
  await page.screenshot({ path: output, fullPage: false });
  await browser.close();
  try { fs.unlinkSync(tmp); } catch {}
})();
