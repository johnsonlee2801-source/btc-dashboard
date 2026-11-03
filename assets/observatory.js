(function(){
  'use strict';
  const M=window.FlowModel,symbol=document.body.dataset.asset||'BTC',isBTC=symbol==='BTC';
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const fmt=(v,d=2)=>finite(v)?v.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:0}):'—';
  const money=v=>!finite(v)?'—':Math.abs(v)>=100000?'$'+(v/1000).toFixed(1)+'k':Math.abs(v)>=1000?'$'+fmt(v,0):'$'+fmt(v,2);
  const kmoney=v=>!finite(v)?'—':Math.abs(v)>=1000?'$'+(v/1000).toFixed(1)+'k':'$'+fmt(v,0);
  const pct=(v,d=1,sign=true)=>finite(v)?(sign&&v>0?'+':'')+v.toFixed(d)+'%':'—';
  const short=v=>!finite(v)?'—':Math.abs(v)>=1e9?fmt(v/1e9,2)+'B':Math.abs(v)>=1e6?fmt(v/1e6,2)+'M':Math.abs(v)>=1e4?fmt(v/1e3,1)+'k':fmt(v,1);
  const signed=v=>!finite(v)?'—':(v>0?'+':v<0?'−':'')+short(Math.abs(v));
  const bj=(s,time=false)=>{const n=Date.parse(s);return Number.isFinite(n)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',...(time?{hour:'2-digit',minute:'2-digit',hour12:false}:{})}).format(n):'日期未知';};
  const md=s=>typeof s==='string'&&s.length>=10?s.slice(5,10).replace('-','/'):'—';
  const opText=op=>({'<':'<','<=':'≤','>':'>','>=':'≥'}[op]||op);
  let data=null,asset=null,quote=null,reserves=null,radar=null,spotFlow=null,trendRange='365',filter='all',reserveWindow='7d';

  const now=()=>Date.now();
  const livePrice=()=>quote?.price??asset?.metrics?.price?.value;

  function showDialog(title,html){$('dialogTitle').textContent=title;$('dialogContent').innerHTML=html;$('infoDialog').showModal();}
  function notice(html){$('dataNotice').innerHTML=html;$('dataNotice').hidden=!html;}

  function valueText(item,v=item?.value){
    if(!finite(v))return '—';
    if(item.key==='hash_ribbon')return v>0?'投降中':'否';
    if(['lth_net30','whale_net30'].includes(item.key))return signed(v);
    if(['supply_profit','sth_profit','drawdown90'].includes(item.key))return fmt(v,1);
    if(['weekly_rsi','fear'].includes(item.key))return fmt(v,0);
    if(item.key==='sopr')return fmt(v,4);
    return fmt(v,2);
  }
  function gapText(item,state){
    if(state===true)return {cls:'met',text:'✓ 已亮'};
    if(state===null)return {cls:'muted',text:finite(item.value)?'数据过期 · 不参与':'暂无可核验数据'};
    const t=M.triggerPrice(item);
    if(t){const mv=M.move(t,livePrice());return {cls:'',text:`需${mv<0?'跌':'涨'} ${pct(Math.abs(mv),1,false)} → ${kmoney(t)}`};}
    if(item.key==='hash_ribbon')return {cls:'',text:'未投降'};
    const g=item.gap;if(!g||!finite(g.delta))return {cls:'',text:''};
    const unit=item.unit.trim()==='%'?' 点':item.unit.trim()?item.unit:'';
    if(['lth_net30','whale_net30'].includes(item.key))return {cls:'',text:'需转为净增加'};
    return {cls:'',text:`差 ${fmt(Math.abs(g.delta),item.key==='sopr'?4:Math.abs(g.delta)<1?2:1)}${unit}`};
  }
  function btLine(bt,compact=true){
    if(!bt)return '回测样本不足';
    if(!bt.litDays)return `${bt.start.slice(0,7)} 起未亮过`;
    const parts=[`亮 ${bt.episodes} 段`];
    if(bt.forwardN&&finite(bt.forwardMedianPct))parts.push(`90天后中位 ${pct(bt.forwardMedianPct,0)}`);
    if(bt.forwardN&&finite(bt.forwardUpPct))parts.push(`上涨 ${bt.forwardUpPct}%`);
    if(!bt.forwardN)parts.push('尚无 90 天后续样本');
    if(!compact)parts.push(`覆盖 ${bt.lowsCovered}/${bt.lows} 个3月低点`);
    return parts.join(' · ');
  }

  // ---------------------------------------------------------------- head & quote
  function renderHead(){
    $('snapshotTime').textContent='研究快照 '+bj(data.generatedAt,true)+' 北京时间';
    const q=quote,m=asset.metrics.price;
    $('price').textContent=money(q?.price??m?.value);
    $('priceChange').innerHTML=q&&finite(q.change24h)?`<b class="${q.change24h>=0?'positive':'negative'}">${esc(pct(q.change24h,2))}</b> 24h`:'';
    $('quoteMeta').textContent=q?`${q.source} 实时 · ${bj(q.asOf,true)}`:`最近日收盘 · ${m?.asOf||'—'}`;
  }

  // ---------------------------------------------------------------- verdict
  function gaugeSVG(value){
    const v=Math.max(0,Math.min(100,value||0)),a=Math.PI*(1-v/100),x=110+78*Math.cos(a),y=112-78*Math.sin(a);
    const arc=(from,to,color)=>`<path d="M20 112 A90 90 0 0 1 200 112" fill="none" stroke="${color}" stroke-width="14" pathLength="100" stroke-dasharray="${to-from} ${100-(to-from)}" stroke-dashoffset="${-from}"/>`;
    return `<svg viewBox="0 0 220 128" class="gauge" aria-hidden="true"><path d="M20 112 A90 90 0 0 1 200 112" fill="none" stroke="#2b3645" stroke-width="14"/>${arc(0,20,'#4b5668')}${arc(20,50,'#d79a45')}${arc(50,60,'#7fd6ad')}${arc(60,100,'#41d69c')}
      <text x="22" y="72" fill="#8998ad" font-size="10">20</text><text x="104" y="16" fill="#8998ad" font-size="10">50</text><text x="148" y="26" fill="#8998ad" font-size="10">60</text>
      <line x1="110" y1="112" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#ecf2fa" stroke-width="4" stroke-linecap="round"/><circle cx="110" cy="112" r="6" fill="#ecf2fa"/></svg>`;
  }
  function renderVerdict(){
    const el=$('verdict');
    if(isBTC){
      const s=M.score(asset.groups,now()),v=M.verdict(s.lower),combo=M.comboState(asset.combo,livePrice());
      const gl=id=>s.groups.find(g=>g.id===id)||{lit:0,total:0};
      const bt50=asset.scoreBacktest?.['50'],bt20=asset.scoreBacktest?.['20'];
      const gapLine=combo?(combo.all?'两条组合条件当前同时满足':`跌破 <b>${esc(kmoney(combo.target))}</b> 两条同时满足，还需跌 <b>${esc(pct(Math.abs(M.move(combo.target,livePrice())),1,false))}</b>`):'组合条件数据待确认';
      const tiers=M.BANDS.slice().reverse().map(([floor,code,label],i,arr)=>`<span class="tier ${code===v.code?'on':''} tier-${code}">${esc(label)}<small>${i<arr.length-1?`${floor}–${arr[i+1][0]-1}`:`≥${floor}`}</small></span>`).join('');
      el.innerHTML=`<div class="verdict-gauge">${gaugeSVG(s.lower)}<div class="gauge-num tabular">${esc(fmt(s.lower,1))}</div><div class="gauge-cap">综合观察指数${s.upper>s.lower?` · 缺失项最多 +${esc(fmt(s.upper-s.lower,1))}`:''}</div></div>
        <div class="verdict-body"><p class="verdict-kicker">现在</p><h2 class="verdict-title v-${v.code}">${esc(v.label)}<span>${combo?.all?'组合信号已亮':'组合信号未亮'}</span></h2>
        <p class="verdict-line">${gapLine}</p>
        <p class="verdict-counts">大底必要 <b>${gl('necessary').lit}/${gl('necessary').total}</b> · 大底确认 <b>${gl('confirm').lit}/${gl('confirm').total}</b> · 相对底部 <b>${gl('relative').lit}/${gl('relative').total}</b> · 有效数据 ${s.known}/${s.total}</p>
        <div class="tiers">${tiers}</div>
        <p class="verdict-evidence">${bt50?.litDays&&bt50.forwardN?`历史依据：指数 ≥50 的 ${bt50.episodes} 段（${esc(bt50.start.slice(0,7))} 起），90 天后中位 ${esc(pct(bt50.forwardMedianPct,0))}、上涨概率 ${bt50.forwardUpPct}%`:''}${bt20?.litDays&&bt20.forwardN?`；指数 ≥20 时 90 天后上涨概率 ${bt20.forwardUpPct}%`:''}。样本只覆盖一轮熊转牛，<button type="button" class="link" data-method>看口径</button></p></div>`;
    }else{
      const s=M.score(asset.groups,now()),items=asset.groups[0].items;
      const near=items.filter(i=>M.itemState(i,now())===false&&M.triggerPrice(i)).map(i=>({label:i.label,t:M.triggerPrice(i)})).sort((a,b)=>b.t-a.t);
      el.innerHTML=`<div class="verdict-gauge"><div class="ring tabular"><b>${s.lit}</b><span>/ ${s.total}</span></div><div class="gauge-cap">ETH 低位条件已满足</div></div>
        <div class="verdict-body"><p class="verdict-kicker">现在</p><h2 class="verdict-title v-${s.lit>=4?'strong':s.lit>=2?'watch':'none'}">${!s.known?'数据暂缺，无法判断':s.lit>=4?'多数低位条件同时满足':s.lit>=2?'部分低位条件满足':s.lit===1?'仅一项低位条件满足':s.known<s.total?'有效条件均未满足（部分数据缺失）':'低位条件均未满足'}</h2>
        <p class="verdict-line">${items.filter(i=>M.itemState(i,now())).map(i=>`<span class="pill on">✓ ${esc(i.label)}</span>`).join('')||'暂无已亮条件'}</p>
        <p class="verdict-counts">${near.length?'最近的价格触发：'+near.slice(0,3).map(n=>`${esc(n.label)} ${esc(kmoney(n.t))}（${esc(pct(M.move(n.t,livePrice()),1))}）`).join(' · '):''}</p>
        <p class="verdict-evidence">ETH 不套用 BTC 的综合分数与矿工/持有者模型；6 项条件各自回测，见下方卡片。有效数据 ${s.known}/${s.total}。<button type="button" class="link" data-method>看口径</button></p></div>`;
    }
  }

  // ---------------------------------------------------------------- combo / nearest triggers
  function barRow(label,target,price,met,sub,extra=''){
    const mv=M.move(target,price),fill=finite(target)&&finite(price)?Math.max(0,Math.min(1,target/price))*100:0;
    return `<div class="bar-row"><div class="bar-head"><span>${label}</span><b class="${met?'positive':'amber'}">${met?'✓ 已满足':finite(mv)?`还需跌 ${esc(pct(Math.abs(mv),1,false))}`:'待确认'}</b></div>
      <div class="bar"><i style="width:${met?100:fill.toFixed(1)}%" class="${met?'met':''}"></i></div>
      <div class="bar-foot"><span>现价 ${esc(kmoney(price))}</span><span>触发 <b class="positive">${esc(kmoney(target))}</b> ${sub}</span></div>${extra}</div>`;
  }
  function renderCombo(){
    const el=$('combo'),price=livePrice();
    if(isBTC){
      const c=asset.combo,st=M.comboState(c,price),bt=c.backtest;
      el.innerHTML=`<div class="panel-title"><h2 id="comboTitle">组合信号：两条都满足才亮</h2><span>${bt?esc(btLine(bt,false)):''}</span></div>
        ${c.conditions.map((x,i)=>barRow(`${i===0?'①':'②'} ${esc(x.label)}`,x.triggerPrice,price,st?.each[i],`<small>（${esc(x.id==='sth'?'STH 成本 · '+md(x.asOf):'90天高 '+kmoney(x.high90)+' × 0.8')}）</small>`)).join('')}
        <p class="panel-note">组合信号在样本期（${esc(bt?.start?.slice(0,7)||'—')} 起）亮过 ${bt?.episodes??'—'} 段，覆盖了 ${bt?.lowsCovered??'—'}/${bt?.lows??'—'} 个 3 个月低点；亮起后 90 天中位 ${esc(pct(bt?.forwardMedianPct,0))}。</p>`;
    }else{
      const items=asset.groups[0].items.filter(i=>(i.linked||i.key==='drawdown90')&&M.itemFresh(i,now()));
      const rows=items.map(i=>{
        const close=asset.metrics.price?.value;
        const t=i.key==='drawdown90'?(asset.ladder.find(r=>r.label.startsWith('90天高点'))?.value):M.triggerPrice(i)??(i.linked&&finite(i.value)&&i.value>0&&finite(close)?close*i.threshold/i.value:null);
        // Status and distance both come from the live price: below the trigger means met.
        return {i,t,state:finite(t)&&finite(price)?price<=t:null};
      }).filter(r=>finite(r.t)).sort((a,b)=>b.t-a.t);
      el.innerHTML=`<div class="panel-title"><h2 id="comboTitle">价格触发线</h2><span>按距离由近到远</span></div>${rows.map(r=>barRow(esc(r.i.label)+` <small>${esc(opText(r.i.op))} ${esc(r.i.threshold)}${esc(r.i.unit)}</small>`,r.t,price,r.state===true,`<small>· ${esc(btLine(r.i.backtest))}</small>`)).join('')}
        <p class="panel-note">触发价 = 当前价格 × 阈值 ÷ 当前指标值（指标与价格同比例变动时成立）。</p>`;
    }
  }

  // ---------------------------------------------------------------- position band (BTC)
  function renderBand(){
    const el=$('band');if(!el)return;
    const b=asset.band&&M.dayFresh(asset.band.asOf,3,now())?asset.band:null;
    if(!b){el.innerHTML='<div class="panel-title"><h2 id="bandTitle">价格位置带</h2></div><p class="panel-note">200 周均线或 STH 成本缺失或已过期，位置带待确认。</p>';return;}
    const zones=[['低于 200 周线',`≤${kmoney(b.ma200w)}`],['200周线–参考线',b.line>b.ma200w?`${kmoney(b.ma200w)}–${kmoney(b.line)}`:'（区间为空）'],['线上 未满28天',`≥${kmoney(b.line)}`],['线上 满28天','持续站稳']];
    el.innerHTML=`<div class="panel-title"><h2 id="bandTitle">价格位置带</h2><span>参考线 = max(200周线 ${esc(kmoney(b.ma200w))}, STH成本 ${esc(kmoney(b.sthCost))})</span></div>
      <div class="zones">${zones.map((z,i)=>`<div class="zone z${i} ${i===b.zone?'on':''}"><b>${esc(z[0])}</b><small>${esc(z[1])}</small>${i===b.zone?'<em>当前</em>':''}</div>`).join('')}</div>
      <p class="panel-note">日收盘 ${esc(kmoney(asset.metrics.price?.value))}${b.zone>=2?`，已连续 ${b.daysAbove} 天收在参考线上方`:''}。位置带只描述价格所处区间，不是买卖指令。</p>`;
  }

  // ---------------------------------------------------------------- trend chart
  function renderTrend(){
    const el=$('trend');
    const all=(asset.scoreHistory||[]).filter(r=>finite(r[1])&&finite(r[2]));
    const rows=trendRange==='365'?all.slice(-365):all;
    const scoreMax=isBTC?100:6;
    const head=`<div class="panel-title"><h2 id="trendTitle">${isBTC?'指数走势':'低位条件数走势'}</h2><div class="seg" role="group" aria-label="时间范围"><button type="button" data-trend="365" aria-pressed="${trendRange==='365'}">近 1 年</button><button type="button" data-trend="all" aria-pressed="${trendRange==='all'}">全部 ${esc(all[0]?.[0]?.slice(0,4)||'')}–</button></div></div>
      <div class="legend"><span><i class="sw amber"></i>${isBTC?'观察指数（左轴）':'满足条件数（左轴）'}</span><span><i class="sw blue"></i>${symbol} 日收盘（右轴）</span>${isBTC?'<span class="muted">虚线 20 / 50 / 60</span>':''}</div>`;
    if(rows.length<10){el.innerHTML=head+'<p class="panel-note">历史数据不足，暂不绘制。</p>';return;}
    const box=document.createElement('div');box.className='chart';el.innerHTML=head;el.append(box);
    const W=Math.max(300,Math.min(900,el.clientWidth-20)),H=230,L=34,R=54,T=14,B=26;
    const t0=Date.parse(rows[0][0]),t1=Date.parse(rows.at(-1)[0]),span=Math.max(1,t1-t0);
    const prices=rows.map(r=>r[2]),pl=Math.min(...prices)*.95,ph=Math.max(...prices)*1.03;
    const x=d=>L+(Date.parse(d)-t0)/span*(W-L-R),ys=v=>T+(1-v/scoreMax)*(H-T-B),yp=v=>T+(ph-v)/(ph-pl)*(H-T-B);
    let g='';
    for(const lv of isBTC?[20,50,60]:[2,4])g+=`<line x1="${L}" x2="${W-R}" y1="${ys(lv)}" y2="${ys(lv)}" stroke="#3a4656" stroke-dasharray="3 4"/><text x="${L-6}" y="${ys(lv)+3}" text-anchor="end" fill="#8c9aaf" font-size="10">${lv}</text>`;
    for(let i=0;i<4;i++){const v=pl+(ph-pl)*i/3;g+=`<text x="${W-R+6}" y="${yp(v)+3}" fill="#7f9ccc" font-size="10">${esc(kmoney(v))}</text>`;}
    const ticks=5;for(let i=0;i<=ticks;i++){const t=t0+span*i/ticks,day=new Date(t).toISOString().slice(0,10);g+=`<text x="${L+(W-L-R)*i/ticks}" y="${H-8}" text-anchor="middle" fill="#8c9aaf" font-size="10">${esc(trendRange==='365'?md(day):day.slice(0,7))}</text>`;}
    const area='M'+rows.map(r=>`${x(r[0]).toFixed(1)} ${ys(r[1]).toFixed(1)}`).join(' L')+` L${x(rows.at(-1)[0]).toFixed(1)} ${ys(0)} L${x(rows[0][0]).toFixed(1)} ${ys(0)} Z`;
    const pline='M'+rows.map(r=>`${x(r[0]).toFixed(1)} ${yp(r[2]).toFixed(1)}`).join(' L');
    const peak=rows.reduce((a,b)=>b[1]>a[1]?b:a,rows[0]);
    const last=rows.at(-1);
    box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(symbol)} ${isBTC?'观察指数':'低位条件数'}与价格，${esc(rows[0][0])} 至 ${esc(last[0])}">${g}
      <path d="${area}" fill="#ffb54733" stroke="#ffb547" stroke-width="1.4"/><path d="${pline}" fill="none" stroke="#70aaff" stroke-width="1.5"/>
      ${peak[1]>0?`<circle cx="${x(peak[0])}" cy="${ys(peak[1])}" r="3.5" fill="#ffb547"/><text x="${Math.min(W-R-90,x(peak[0])+6)}" y="${ys(peak[1])+(ys(peak[1])<T+14?12:-6)}" fill="#ffd28a" font-size="10">${esc(peak[0])} 峰值 ${esc(fmt(peak[1],1))}</text>`:''}
      <circle cx="${x(last[0])}" cy="${ys(last[1])}" r="4" fill="#ffb547" stroke="#151c26" stroke-width="2"/>
      <line class="xh" x1="0" x2="0" y1="${T}" y2="${H-B}" stroke="#a6b5c8" stroke-dasharray="3 3" visibility="hidden"/><rect class="hit" x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}" fill="transparent"/></svg><div class="chart-tip" hidden></div>`;
    const svg=box.querySelector('svg'),tip=box.querySelector('.chart-tip'),xh=box.querySelector('.xh');
    box.querySelector('.hit').addEventListener('pointermove',e=>{
      const b=svg.getBoundingClientRect(),vx=(e.clientX-b.left)/b.width*W,target=t0+(vx-L)/(W-L-R)*span;
      let best=0;for(let i=1;i<rows.length;i++)if(Math.abs(Date.parse(rows[i][0])-target)<Math.abs(Date.parse(rows[best][0])-target))best=i;
      const r=rows[best];tip.textContent=`${r[0]}　${isBTC?'指数 '+fmt(r[1],1):'满足 '+r[1]+' 项'}　${money(r[2])}`;tip.hidden=false;
      tip.style.left=Math.min(box.clientWidth-200,Math.max(4,e.clientX-box.getBoundingClientRect().left-90))+'px';
      xh.setAttribute('x1',x(r[0]));xh.setAttribute('x2',x(r[0]));xh.setAttribute('visibility','visible');
    });
    box.querySelector('.hit').addEventListener('pointerleave',()=>{tip.hidden=true;xh.setAttribute('visibility','hidden');});
    const note=document.createElement('p');note.className='panel-note';
    note.textContent=isBTC?`指数按每天当时可得的数据重算（链上数据 ${all[0][0]} 起），缺失项计 0。当前 ${fmt(last[1],1)}，样本内峰值 ${fmt(peak[1],1)}（${peak[0]}）。`:`每天满足的低位条件数（价格类 2017 年起，ETH MVRV 自数据起始日起）。`;
    el.append(note);
    el.querySelectorAll('[data-trend]').forEach(b=>b.addEventListener('click',()=>{trendRange=b.dataset.trend;renderTrend();}));
  }

  // ---------------------------------------------------------------- signal groups
  function renderGroups(){
    const s=M.score(asset.groups,now());
    const bar=`<div class="section-bar"><div><h2>信号矩阵</h2><p>${isBTC?`16 项，每项只计一次；权重 必要 40 · 确认 40 · 相对 20`:'6 项 ETH 低位条件'}。点卡片看来源、日期与回测。</p></div><div class="seg" role="group" aria-label="筛选"><button type="button" data-filter="all" aria-pressed="${filter==='all'}">全部</button><button type="button" data-filter="lit" aria-pressed="${filter==='lit'}">已亮</button><button type="button" data-filter="missing" aria-pressed="${filter==='missing'}">缺失/过期</button></div></div>`;
    $('groups').innerHTML=bar+asset.groups.map((g,gi)=>{
      const gs=s.groups[gi],per=g.weight?g.weight/g.items.length:0;
      const items=g.items.filter(i=>{const st=M.itemState(i,now());return filter==='all'||filter==='lit'&&st===true||filter==='missing'&&st===null;});
      return `<section class="panel group"><div class="group-head"><h3>${esc(g.title)} <b class="${gs.lit?'positive':''}">${gs.lit}</b><small>/${gs.total} 亮</small></h3><span>${esc(g.description)}${per?` · 每项 ${fmt(per,1)} 分`:''}</span></div>
        <div class="cards ${g.items.length===6?'n6':''}">${items.length?items.map(i=>{
          const st=M.itemState(i,now()),gp=gapText(i,st);
          return `<button type="button" class="card ${st===true?'lit':st===null?'na':''}" data-g="${gi}" data-k="${esc(i.key)}"><span class="card-label"><i></i>${esc(i.label)}</span>
            <span class="card-value tabular">${esc(valueText(i))}${finite(i.value)&&i.unit.trim()==='%'?'<small>%</small>':''}<em>${esc(opText(i.op))}${esc(i.threshold)}${esc(i.unit.trim()==='%'?'%':'')}</em></span>
            <span class="card-gap ${gp.cls}">${esc(gp.text)}</span><span class="card-bt">${esc(btLine(i.backtest))}</span><span class="card-src">${esc(i.source)} · ${esc(md(i.asOf))}</span></button>`;
        }).join(''):'<p class="panel-note">没有符合筛选的指标。</p>'}</div></section>`;
    }).join('');
    $('groups').querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;renderGroups();}));
    $('groups').querySelectorAll('.card').forEach(b=>b.addEventListener('click',()=>detail(asset.groups[+b.dataset.g].items.find(i=>i.key===b.dataset.k))));
  }
  function detail(i){
    const st=M.itemState(i,now()),gp=gapText(i,st),bt=i.backtest;
    showDialog(i.label,`<div class="detail-value tabular">${esc(valueText(i))}<small> ${esc(i.unit)}</small></div>
      <table><tr><th>触发线</th><td>${esc(opText(i.op))} ${esc(i.threshold)}${esc(i.unit)}</td></tr><tr><th>当前状态</th><td>${st===true?'已亮':st===false?'未亮 · '+esc(gp.text):'数据缺失或过期，不参与判断'}</td></tr>
      <tr><th>数据日期</th><td>${esc(i.asOf||'—')}（有效期 ${i.maxAgeDays} 天）</td></tr><tr><th>来源</th><td>${i.sourceUrl?`<a href="${esc(i.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(i.source)}</a>`:esc(i.source||'—')}</td></tr></table>
      ${i.note?`<p>${esc(i.note)}</p>`:''}
      <h3>历史回测</h3>${bt?`<table><tr><th>样本区间</th><td>${esc(bt.start)} → ${esc(bt.end)}（${bt.sampleDays} 天）</td></tr><tr><th>亮起</th><td>${bt.litDays} 天，${bt.episodes} 段（间隔 >7 天算新的一段）</td></tr>
      <tr><th>亮起后 90 天</th><td>${bt.forwardN?`中位 ${esc(pct(bt.forwardMedianPct,1))}，上涨占比 ${bt.forwardUpPct}%（${bt.forwardN} 个可观测日）`:'样本末端，尚无 90 天后数据'}</td></tr>
      <tr><th>覆盖 3 月低点</th><td>${bt.lowsCovered} / ${bt.lows}（低点 ±7 天内亮过）</td></tr><tr><th>亮时靠近低点</th><td>${finite(bt.nearLowPct)?bt.nearLowPct+'% 的亮起日距某个 3 月低点 ≤30 天':'—'}</td></tr></table>
      <p class="muted">3 月低点 = 前后各 45 天内的最低收盘。回测基于同一公开数据源，样本有限，历史表现不代表未来。</p>`:'<p>该指标历史数据不足，暂未回测。</p>'}`);
  }

  // ---------------------------------------------------------------- side panels
  function renderLadder(){
    const p=livePrice();
    $('ladder').innerHTML=`<div class="panel-title"><h2 id="ladderTitle">价格阶梯</h2><span>跌到哪里点亮什么</span></div><div class="ladder">${(asset.ladder||[]).map(r=>{
      const self=r.label==='最近日收盘',mv=self?null:M.move(r.value,p),below=finite(p)&&p<r.value;
      return `<div class="rung ${self?'self':''}"><span><i class="${self?'blue':below?'green':''}"></i>${esc(r.label)}<small>${esc(r.meaning)}${r.meaning?' · ':''}${esc(md(r.asOf))}</small></span><b class="tabular">${esc(kmoney(r.value))}</b><em class="${below&&!self?'positive':''}">${self?'日收盘':esc(pct(mv,1))}</em></div>`;
    }).join('')}</div><p class="panel-note">百分比相对实时价格。绿色 = 价格已在该线下方。</p>`;
  }
  function renderSpotFlow(){
    const el=$('spotflow');if(!el)return;
    const days=spotFlow?.assets?.[symbol]?.days||[],last=days.at(-1);
    const head=`<div class="panel-title"><h2 id="spotflowTitle">现货资金流</h2><span>Binance ${esc(symbol)}/USDT · 按单笔成交金额</span></div>`;
    if(!last){el.innerHTML=head+'<p class="panel-note">暂无可核验数据。</p>';return;}
    const age=(now()-Date.parse(last.date+'T00:00:00Z'))/86400000,ok=age>=0&&age<=3;
    const b=last.buckets,small=b.lt10k.net,big=b['10k_100k'].net+b['100k_1m'].net+b.gt1m.net;
    const usd=v=>(v>=0?'+':'−')+'$'+short(Math.abs(v));
    const max=Math.max(1,...Object.values(b).map(x=>Math.abs(x.net)));
    const rows=(spotFlow.buckets||[]).map(k=>{const v=b[k.key]?.net??0;
      return `<div class="sf-row"><span>${esc(k.label)}</span><div class="sf-bar"><i class="${v<0?'neg':'pos'}" style="width:${(Math.abs(v)/max*50).toFixed(1)}%;${v<0?'right':'left'}:50%"></i></div><b class="tabular ${v<0?'negative':'positive'}">${esc(usd(v))}</b></div>`;}).join('');
    const cutoff=Date.parse(last.date+'T00:00:00Z')-6*86400000;
    const week=days.filter(d=>Date.parse(d.date+'T00:00:00Z')>=cutoff),wmax=Math.max(1,...week.map(d=>Math.abs(d.net-d.buckets.lt10k.net)));
    const bars=week.map(d=>{const v=d.net-d.buckets.lt10k.net;return `<div title="${esc(d.date)} 大单净额 ${esc(usd(v))}"><span class="${v<0?'neg':''}" style="height:${(Math.abs(v)/wmax*46).toFixed(1)}%;${v>=0?'bottom':'top'}:50%"></span><small>${esc(md(d.date))}</small></div>`;}).join('');
    el.innerHTML=`${head}<div class="sf-head"><div><small>散户 &lt;1万</small><b class="tabular ${small<0?'negative':'positive'}">${esc(usd(small))}</b></div><div><small>大单 ≥1万</small><b class="tabular ${big<0?'negative':'positive'}">${esc(usd(big))}</b></div></div>
      <div class="sf-rows">${rows}</div><p class="panel-note" style="padding-bottom:4px">近 7 日大单（≥1万）净额</p><div class="flow-bars sf-week">${bars}</div>
      <p class="panel-note">UTC ${esc(last.date)}${ok?'':' · 已过期'}。净额 = 主动买入 − 主动卖出（USDT）。按单笔聚合成交分档，跨价位的大单会被拆分，大单金额偏保守。<a href="${esc(spotFlow.sourceUrl)}" target="_blank" rel="noopener noreferrer">Binance 公开数据 ↗</a></p>`;
  }
  function renderFlows(){
    const e=asset.etf;
    if(!e?.rows?.length){$('flows').innerHTML='<div class="panel-title"><h2 id="flowsTitle">现货 ETF 资金流</h2></div><p class="panel-note">暂无可核验数据。</p>';return;}
    const rows=e.rows.slice(-5),sum=rows.reduce((s,r)=>s+r.value,0),max=Math.max(1,...rows.map(r=>Math.abs(r.value)));
    const age=(now()-Date.parse(e.asOf))/86400000,ok=age>=0&&age<=5;
    $('flows').innerHTML=`<div class="panel-title"><h2 id="flowsTitle">现货 ETF 资金流</h2><span>${esc(symbol)} · 5 个交易日</span></div>
      <div class="flow-sum ${ok?(sum>=0?'positive':'negative'):'muted'} tabular">${sum>=0?'+':'−'}$${esc(short(Math.abs(sum)*1e6))}</div>
      <div class="flow-bars">${rows.map(r=>`<div title="${esc(r.date)}: ${esc(fmt(r.value,1))} 百万美元"><span class="${r.value<0?'neg':''}" style="height:${(Math.abs(r.value)/max*46).toFixed(1)}%;${r.value>=0?'bottom':'top'}:50%"></span><small>${esc(md(r.date))}${r.provisional?'*':''}</small><em class="${r.value<0?'negative':'positive'}">${esc(fmt(r.value,0))}</em></div>`).join('')}</div>
      <p class="panel-note"><a href="${esc(e.sourceUrl)}" target="_blank" rel="noopener noreferrer">Farside ↗</a> · 截至 ${esc(e.asOf)}（美东收盘后更新，单位百万美元）${rows.some(r=>r.provisional)?'。* 为暂定数据，晚报的基金补齐后会修订':''}${ok?'':' · 已过期'}</p>`;
  }
  function spark(points,cls=''){
    const v=(points||[]).map(p=>p[1]).filter(finite);if(v.length<2)return '';
    const lo=Math.min(...v),hi=Math.max(...v),W=120,H=28,x=i=>i/(v.length-1)*W,y=n=>H-2-(hi===lo?.5:(n-lo)/(hi-lo))*(H-4);
    return `<svg class="spark ${cls}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path d="M${v.map((n,i)=>`${x(i).toFixed(1)} ${y(n).toFixed(1)}`).join(' L')}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
  }
  function renderCohorts(){
    const el=$('cohorts');if(!el)return;
    const c=asset.cohorts||{},order=['whale_1k_10k','whale_10k_plus','retail_lt1','lth_net30'];
    const stale=k=>!c[k]||!M.dayFresh(c[k].asOf,6,now());
    const rows=order.filter(k=>c[k]).map(k=>{const r={...c[k],stale:stale(k)},d30=k==='lth_net30'?r.value:r.d30;
      return `<div class="cohort${r.stale?' na':''}"><div><b>${esc(r.label)}</b><small>${esc(r.note)} · ${esc(md(r.asOf))}${r.stale?' · 已过期':''}</small></div><div class="cohort-num"><b class="${finite(d30)?(d30>=0?'positive':'negative'):'muted'} tabular">${esc(signed(d30))}</b><small>30天${k==='lth_net30'?'净变化':''}${finite(r.d7)?` · 7天 ${esc(signed(r.d7))}`:''}</small></div>${spark(r.spark,finite(d30)&&d30<0?'neg':'pos')}</div>`;}).join('');
    const w=c.whale_1k_10k?.d30,rt=c.retail_lt1?.d30;
    const headline=finite(w)&&finite(rt)&&!stale('whale_1k_10k')&&!stale('retail_lt1')?`${w>=0?'巨鲸增持':'巨鲸减持'} / ${rt>=0?'散户增持':'散户减持'}`:'';
    el.innerHTML=`<div class="panel-title"><h2 id="cohortsTitle">巨鲸 vs 散户</h2><span>BGeometrics 地址口径</span></div>${headline?`<p class="cohort-headline">${esc(headline)}</p>`:''}${rows||'<p class="panel-note">分组数据正在首次回补（免费接口每天限额 15 次，约 1–2 天补齐）。</p>'}
      <p class="panel-note">按地址余额分组，单位 BTC。交易所和托管机构也有大额地址，"巨鲸"不等于个人实体。</p>`;
  }
  function renderFacts(){
    const el=$('facts');if(!el)return;
    el.innerHTML=`<div class="panel-title"><h2 id="factsTitle">ETH 链上事实</h2><span>不计入低位条件</span></div><div class="facts">${(asset.facts||[]).map(f=>{
      const ok=M.fresh(f);const v=['holder_count','active_addr_7d','total_staked'].includes(f.key)?short(f.value):fmt(f.value,2);
      return `<div class="fact ${ok?'':'na'}" title="${esc(f.note||'')}"><span>${esc(f.label)}</span><b class="tabular">${esc(finite(f.value)?v:'—')}<small>${esc(f.unit)}</small></b><small>${esc(f.source)} · ${esc(f.asOf?md(f.asOf):'—')}${ok?'':' · 过期'}</small></div>`;}).join('')}</div>`;
  }
  function renderPositioning(){
    const d=asset.derivatives||{},ls=d.long_short,tp=d.top_position,fr=d.funding;
    const row=(label,m,fmtv,extra)=>`<div class="pos-row"><span>${label}</span><b class="tabular ${M.fresh(m)?'':'muted'}">${M.fresh(m)?fmtv:'—'}</b><small>${M.fresh(m)?extra:'暂无有效数据'}</small></div>`;
    const div=radar?.divergence?.slice(0,3)||[];
    $('positioning').innerHTML=`<div class="panel-title"><h2 id="positioningTitle">合约持仓</h2><span>Binance ${esc(symbol)}USDT 永续</span></div>
      ${row('大户持仓多空比',tp,fmt(tp?.value,2),`多 ${fmt(tp?.longPct,1)}% · 30天前 ${fmt(tp?.ago30,2)}`)}
      ${row('全体账户多空人数比',ls,fmt(ls?.value,2),`多 ${fmt(ls?.longPct,1)}% · 30天前 ${fmt(ls?.ago30,2)}`)}
      ${row('资金费率 / 期',fr,fmt(fr?.value,4)+'%',`年化约 ${fmt(fr?.value*3*365,1)}%`)}
      <p class="panel-note">${M.fresh(tp)&&M.fresh(ls)?(tp.longPct<ls.longPct?'散户比大户更偏多。':'大户比散户更偏多。'):''}合约多头不等于现货买入。</p>
      ${div.length?`<div class="radar-mini"><b>全市场大户/散户方向分歧</b>${div.map(r=>`<span>${esc(r.baseAsset)} <small>大户多 ${esc(fmt(r.topLong*100,0))}% · 散户多 ${esc(fmt(r.accountLong*100,0))}%</small></span>`).join('')}</div>`:''}
      <a class="panel-link" href="/positioning-radar">查看全市场资金雷达 →</a>`;
  }
  function renderReserves(){
    const rows=reserves?.assets?.[symbol]?.exchanges;
    if(!Array.isArray(rows)||!rows.length){$('reserves').innerHTML='<div class="panel-title"><h2 id="reservesTitle">交易所公开储备</h2></div><p class="panel-note">暂无可核验数据。</p>';return;}
    const ok=(now()-Date.parse(reserves.anchor))/3600000<=60;
    $('reserves').innerHTML=`<div class="panel-title"><h2 id="reservesTitle">交易所公开储备</h2><div class="seg" role="group" aria-label="变化窗口">${['7d','30d','90d'].map(w=>`<button type="button" data-rw="${w}" aria-pressed="${w===reserveWindow}">${w.replace('d',' 天')}</button>`).join('')}</div></div>
      ${[...rows].sort((a,b)=>b.latest-a.latest).slice(0,5).map(r=>{const v=r.change?.[reserveWindow],f=M.reserveFresh(reserves.anchor,r);
        return `<div class="pos-row"><span>${esc(r.name)}</span><b class="tabular ${f&&finite(v)?(v>=0?'positive':'negative'):'muted'}">${esc(signed(v))}</b><small>余额 ${esc(short(r.latest))} ${esc(symbol)} · ${esc(md(r.asOf))}${f?'':' · 已过期，不作当前变化'}</small></div>`;}).join('')}
      <p class="panel-note">DefiLlama 公开地址口径，${esc(md(reserves.anchor))}${ok?'':' · 已过期'}。剔除单日 >20% 的地址台阶；储备变化不等于交易净流入。</p>`;
    $('reserves').querySelectorAll('[data-rw]').forEach(b=>b.addEventListener('click',()=>{reserveWindow=b.dataset.rw;renderReserves();}));
  }
  function renderSentiment(){
    const s=asset.sentiment||{},d=asset.derivatives||{};
    const cell=(label,m,val,sub,cls='')=>`<div class="senti ${M.fresh(m)?'':'na'}"><span>${label}</span><b class="tabular ${cls}">${M.fresh(m)?val:'—'}</b><small>${M.fresh(m)?sub:'暂无有效数据'}</small><small class="src">${esc(m?.source||'')}${m?.asOf?' · '+esc(bj(m.asOf,!/T00:00/.test(m.asOf))):''}</small></div>`;
    const dd=(m)=>finite(m?.prev)?`较昨日 ${m.value-m.prev>=0?'▲':'▼'}${fmt(Math.abs(m.value-m.prev),0)}`:'';
    const cells=[];
    if(s.fear)cells.push(cell('恐慌贪婪 · Alternative',s.fear,fmt(s.fear.value,0),dd(s.fear),s.fear.value<=25?'positive':s.fear.value>=75?'negative':''));
    if(s.cmc_fear)cells.push(cell('恐慌贪婪 · CMC',s.cmc_fear,fmt(s.cmc_fear.value,0),dd(s.cmc_fear),s.cmc_fear.value<=25?'positive':s.cmc_fear.value>=75?'negative':''));
    cells.push(cell('资金费率 / 期',d.funding,fmt(d.funding?.value,4)+'%',`年化 ${fmt(d.funding?.value*1095,1)}%`));
    cells.push(cell('多空人数比',d.long_short,fmt(d.long_short?.value,2),finite(d.long_short?.ago30)?`30天前 ${fmt(d.long_short.ago30,2)}`:''));
    cells.push(cell('25Δ 风险逆转',d.rr25,fmt(d.rr25?.value,2),d.rr25?.value<0?'看跌期权更贵':'看涨期权更贵',d.rr25?.value<0?'negative':'positive'));
    cells.push(cell('DVOL 隐含波动率',d.dvol,fmt(d.dvol?.value,1),finite(d.dvol?.ago30)?`30天前 ${fmt(d.dvol.ago30,1)}`:''));
    $('sentiment').innerHTML=`<div class="panel-title"><h2 id="sentimentTitle">情绪与衍生品</h2><span>恐慌低 = 恐慌（底部信号常见环境）；情绪指数为 BTC 市场口径</span></div><div class="senti-grid">${cells.join('')}</div>`;
  }

  // ---------------------------------------------------------------- notices, method, wiring
  function renderNotice(){
    const items=asset.groups.flatMap(g=>g.items),missing=items.filter(i=>M.itemState(i,now())===null);
    const age=(now()-Date.parse(data.generatedAt))/3600000;
    const parts=[];
    if(age>14)parts.push(`研究快照已 ${Math.floor(age)} 小时未更新，过期数据按原日期显示。`);
    if(missing.length)parts.push(`${missing.length} 项信号数据缺失或过期（${missing.map(i=>i.label).join('、')}），这些项不计为"未亮"，指数按 0 计。`);
    notice(parts.length?'<strong>数据说明</strong>　'+esc(parts.join(' ')):'');
  }
  function render(){
    renderHead();renderVerdict();renderCombo();if(isBTC)renderBand();renderTrend();renderGroups();
    renderLadder();renderFlows();renderSpotFlow();if(isBTC)renderCohorts();else renderFacts();renderPositioning();renderReserves();renderSentiment();renderNotice();
  }
  function methodHTML(){
    return `<h3>综合观察指数（BTC）</h3><p>16 项信号分三组：大底必要 5 项（共 40 分）、大底确认 6 项（共 40 分）、相对底部 5 项（共 20 分），同一指标只出现一次。只有数据有效且满足阈值才计分；缺失或过期项计 0，但单独标注"最多还可能 +X 分"。分档：&lt;20 无底部信号，20–49 进入关注区，50–59 低位信号增强，≥60 历史低位信号集中。分档是观察描述，不是买卖指令。</p>
    <h3>组合信号</h3><p>两条同时满足才亮：① 价格跌破短期持有者成本（STH 实现价格）；② 价格距近 90 个完整日收盘高点跌 ≥20%。触发价 = min(STH 成本, 90 天高点 × 0.8)。</p>
    <h3>触发价怎么算</h3><p>Mayer、价/200周线、MVRV、价/LTH 成本、STH-MVRV 都等于"价格 ÷ 某个成本或均线"，短期内分母几乎不动，所以触发价 = 当前价 × 阈值 ÷ 当前值。其余指标（如盈利占比、RSI、SOPR）与价格不是简单比例，只显示"差多少"。</p>
    <h3>回测</h3><p>对每项信号：统计样本期内亮起的天数与段数（间隔 >7 天算新的一段）；亮起后 90 天的价格变化（中位数、上涨占比）；以及覆盖了多少个"3 个月低点"（前后各 45 天内最低收盘，低点前后 7 天内亮过即算覆盖）。价格类信号用 Binance 2017 年起的日线；链上类信号用 BGeometrics 免费接口可得的 2022-11 起数据，样本只覆盖一轮熊转牛，结论需谨慎。</p>
    <h3>数据与时效</h3><p>价格：Binance 完整 UTC 日收盘（USDT 计价）。链上：BGeometrics（免费接口约有 1–5 天延迟，按实际日期判断时效）。STH-MVRV、价/LTH 成本由本站用价格与 BGeometrics 成本自算。哈希带由全网哈希率 30/60 日均线计算；Pi Cycle 底部 = 150 日 EMA ÷ (0.745 × 471 日均线)。25Δ 风险逆转由 Deribit 期权标记 IV 计算并插值到 30 天。日度信号默认 3–4 天有效（ETH MVRV 因发布延迟为 8 天），周线指标按日展开后 2 天、情绪 2 天、合约 12 小时；过期即不参与判断。回测与指数历史按数据实际发布日计算：BGeometrics 链上数据晚 1 天，ETH MVRV 晚 6 天。</p>
    <h3>阈值与口径差异</h3><p>阈值沿用常见的链上研究口径；MVRV Z-Score 不同数据商的标准差算法不同，本站使用 BGeometrics 口径并以 &lt;0 为阈值（该口径在 2022 年底部约为 −0.1）。巨鲸/散户为地址余额分组，含交易所与托管地址。</p><p>仅作研究参考，不构成投资建议。</p>`;
  }
  async function loadQuote(){
    try{const r=await fetch(`/api/ticker?symbol=${symbol}`,{signal:AbortSignal.timeout(8000)});if(!r.ok)throw 0;const q=await r.json();
      if(q?.symbol===symbol&&finite(q.price)&&q.price>0&&Math.abs(now()-Date.parse(q.asOf))<180000)quote=q;else quote=null;}catch{quote=null;}
    if(asset)keepFocus(()=>{renderHead();renderVerdict();renderCombo();renderLadder();renderGroups();});
  }
  async function load(){
    $('refresh').disabled=true;
    try{
      const r=await fetch('/data/observatory.json',{cache:'no-store',signal:AbortSignal.timeout(15000)});
      if(!r.ok)throw Error('snapshot');const next=await r.json();
      if(next.schemaVersion!==2||!Array.isArray(next.assets?.[symbol]?.groups))throw Error('schema');
      data=next;asset=next.assets[symbol];render();
      const side=await Promise.allSettled([
        fetch('/data/cex-reserves.json',{signal:AbortSignal.timeout(8000)}).then(x=>x.ok?x.json():null),
        fetch('/data/positioning-summary.json',{cache:'no-store',signal:AbortSignal.timeout(8000)}).then(x=>x.ok?x.json():null),
        fetch('/data/spot-flow.json',{cache:'no-store',signal:AbortSignal.timeout(8000)}).then(x=>x.ok?x.json():null)]);
      reserves=side[0].value||null;const rs=side[1].value;spotFlow=side[2].value||null;
      radar=rs&&Date.now()-rs.generatedAt<6*3600000?rs:null;
      renderReserves();renderPositioning();renderSpotFlow();
      await loadQuote();
    }catch{
      if(asset){render();notice('<strong>更新未成功</strong>　保留上次读取的快照，时效仍按实际日期判断。');}
      else{notice('<strong>暂时无法读取数据</strong>　请稍后点击刷新。没有数据时不生成任何观察结论。');$('verdict').innerHTML='<p class="loading">研究快照读取失败。</p>';}
    }finally{$('refresh').disabled=false;}
  }
  $('refresh').addEventListener('click',load);
  document.addEventListener('click',e=>{if(e.target.closest('[data-method]'))showDialog('口径与回测方法',methodHTML());});
  $('sourcesButton').addEventListener('click',()=>showDialog('数据来源',`<p>每个信号卡片都能点开看原始日期与来源。研究快照每 6 小时生成；行情每 30 秒刷新。</p><h3>使用的公开来源</h3><table>${(data?.sources||[]).map(s=>`<tr><td><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a></td></tr>`).join('')}</table>${data?.errors?.length?`<h3>本次快照的源请求失败</h3><p>${data.errors.slice(0,8).map(e=>esc(e.error+' · '+e.url.replace(/^https?:\/\//,'').slice(0,70))).join('<br>')}</p><p>失败的项保留原观测日期，按原日期判断是否过期。</p>`:''}`));
  $('closeDialog').addEventListener('click',()=>$('infoDialog').close());
  $('infoDialog').addEventListener('click',e=>{if(e.target===$('infoDialog'))$('infoDialog').close();});
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(asset)renderTrend();},200);});
  // Re-render (not just the quote) so every section re-judges its validity window over time.
  function keepFocus(fn){
    const a=document.activeElement,key=a?.dataset?.k?`[data-k="${a.dataset.k}"]`:a?.dataset?.filter?`[data-filter="${a.dataset.filter}"]`:null;
    fn();
    if(key)document.querySelector(key)?.focus();
  }
  setInterval(()=>{if(!document.hidden&&asset)loadQuote();},30000);
  setInterval(()=>{if(!document.hidden&&asset)keepFocus(render);},300000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&asset)keepFocus(()=>{render();loadQuote();});});
  load();
})();
