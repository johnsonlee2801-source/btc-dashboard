(function(){
  'use strict';
  const M=window.FlowModel,symbol=document.body.dataset.asset||'BTC',isBTC=symbol==='BTC';
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(v,d=2)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-US',{maximumFractionDigits:d}):'—';
  const money=(v,compact=false)=>typeof v==='number'&&Number.isFinite(v)?'$'+(compact&&v>=10000?(v/1000).toFixed(1)+'k':fmt(v,v>=1000?0:2)):'—';
  const date=(s,time=false)=>{const n=Date.parse(s);return Number.isFinite(n)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',...(time?{hour:'2-digit',minute:'2-digit',hour12:false}:{})}).format(n):'日期未知';};
  const short=(v)=>v==null?'—':Math.abs(v)>=1e9?fmt(v/1e9,2)+'B':Math.abs(v)>=1e6?fmt(v/1e6,2)+'M':Math.abs(v)>=10000?fmt(v/1000,1)+'k':fmt(v,2);
  let data=null,asset=null,range=365,filter='all',lastQuote=null,reserves=null,reserveWindow='7d';
  const methodHTML=`<h3>这套面板怎样阅读</h3><p>本网站采用参考图中的指标与阈值，组成 FlowHunt 自己的公开数据观察框架。未复制原作者的完整模型，也没有可复核的历史回测，因此不显示命中率或误报率。</p>
    <h3>BTC 分数：缺失项保留为未知</h3><p>必要信号 5 项各 8 分（共 40）；确认信号 8 项各 5 分（共 40）；相对信号 8 项各 2.5 分（共 20）。第八项相对信号采用参考图中的「距 90 天高点回撤至少 20%」。同一指标可能出现在不同观察层，不代表独立证据。</p><p>区间下界只计有效且已触发的分数；上界再加所有缺失或过期项的可能分数。缺失项不会当成「未触发」或零分。绿色仅表示该阈值已满足，不代表交易指令。</p>
    <h3>组合条件与位置带</h3><p>组合信号需要同时满足：价格低于有效的 STH 成本、相对近 90 个完整日收盘高点回撤至少 20%。完整数据下，位置带参考线 = max(200 周均线, STH 成本)。缺任一条件则不推断完整位置带；200 周均线使用完整 UTC 周收盘均值。</p><p>四个研究区间为200周线以下、200周线至参考线、线上不足28个完整日、线上至少28个完整日。参考线下的位置可以用有效当日数据确认；当前公开源缺少完整 STH 成本历史，后两个持续性状态不推断。这不是定投执行指令。</p>
    <h3>时间与口径</h3><p>历史图使用 Binance BTC/USDT 或 ETH/USDT 的完整 UTC 日收盘价与 200 日均线；这是 USDT 报价参考，并非严格的美元兑付价格。周 RSI 使用完整 UTC 周收盘与 Wilder 14 周平滑。顶部现价单独来自实时行情 API，不静默改写日度信号。90 天回撤使用收盘高点，未使用日内最高价。</p><p>日度指标通常有效 72 小时；周线指标有效 9 天；情绪 48 小时；合约数据 12 小时。未来时间、缺失时间及过期值不参与触发。免费链上接口存在约 7 天延迟，按实际日期显示，不伪装成当日数据。</p>
    <h3>ETH 独立面板</h3><p>ETH 只采用自身的价格技术观察及网络、供给、质押数据；不套用 BTC 的 100 分制、矿工指标、STH 模型或 Bitcoin 恐慌指数。技术阈值仅作研究观察，未做 ETH 历史胜率验证。</p>
    <h3>不做口径替换</h3><p>地址持仓不等于实体持仓，交易所储备变化不等于巨鲸净买入。没有已核验的实体口径数据时，巨鲸/散户及 LTH/STH 资金流保持缺失。Pi Cycle 底部、矿工收入/成本等缺少完整公式或可靠数据，也不会用近似指标冒充。</p><p>仅作研究参考，不构成投资建议。</p>`;

  function showDialog(title,html){$('dialogTitle').textContent=title;$('dialogContent').innerHTML=html;$('infoDialog').showModal();}
  function notice(html){$('dataNotice').innerHTML=html;$('dataNotice').hidden=!html;}
  function metricStatus(m){return !m||m.value==null?'暂无数据':M.fresh(m)?'有效':Date.parse(m.asOf)>Date.now()?'日期异常':'已过期';}
  function valueText(key,m,unit=''){
    if(!m||m.value==null)return '—';
    if(['holder_count','active_addr_7d','total_staked','lth_net30','whale_net30'].includes(key))return short(m.value);
    if(key==='hash_ribbon')return m.value>0?'是':'否';
    if(key==='funding')return fmt(m.value,4);
    if(['supply_profit','sth_profit','staked_pct','stake_conc_top5','whale_top100_pct','burn_issuance_pct','drawdown90'].includes(key))return fmt(m.value,1);
    return fmt(m.value,['weekly_rsi','fear'].includes(key)?0:key==='sopr'?4:2);
  }
  function metricDetail(item){
    const m=asset.metrics[item.key],status=metricStatus(m),state=M.signal(item,asset.metrics);
    const threshold=item.op?`${item.op.replace('<=','≤').replace('>=','≥')} ${item.threshold}${item.unit||''}`:'结构数据，不设交易阈值';
    showDialog(item.label,`<div class="detail-value">${esc(valueText(item.key,m))}<small> ${esc(item.unit)}</small></div>
      <div class="detail-row"><span>当前状态</span><strong>${esc(status)}${item.op&&state!==null?' · '+(state?'已触发':'未触发'):''}</strong></div>
      <div class="detail-row"><span>观察条件</span><strong>${esc(threshold)}</strong></div>
      <div class="detail-row"><span>数据时间</span><strong>${esc(m?.asOf||'暂无有效日期')} · 原始时区</strong></div>
      <div class="detail-row"><span>数据来源</span><strong>${m?.sourceUrl?`<a href="${esc(m.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(m.source)}</a>`:'暂无已核验公开来源'}</strong></div>
      <p style="margin-top:16px">${esc(m?.note||'仅按有效数据判断阈值；点击关闭后可继续查看其他指标。')}</p>
      <p style="margin-top:12px">缺失与过期不表示未触发。仅作研究参考，不构成投资建议。</p>`);
  }
  function drawGauge(value,label,caption){
    const angle=Math.PI*(1-Math.max(0,Math.min(100,value||0))/100);
    const x=120+84*Math.cos(angle),y=133-84*Math.sin(angle);
    $('gaugeGraphic').innerHTML=`<svg class="gauge-svg" viewBox="0 0 240 160" aria-hidden="true">
      <path d="M20 133 A100 100 0 0 1 220 133" fill="none" stroke="#303c4c" stroke-width="13" pathLength="100"/>
      <path d="M20 133 A100 100 0 0 1 220 133" fill="none" stroke="#df9251" stroke-width="13" pathLength="100" stroke-dasharray="20 80"/>
      <path d="M20 133 A100 100 0 0 1 220 133" fill="none" stroke="#ffb547" stroke-width="13" pathLength="100" stroke-dasharray="29 71" stroke-dashoffset="-21"/>
      <path d="M20 133 A100 100 0 0 1 220 133" fill="none" stroke="#7cd6ab" stroke-width="13" pathLength="100" stroke-dasharray="9 91" stroke-dashoffset="-51"/>
      <path d="M20 133 A100 100 0 0 1 220 133" fill="none" stroke="#41d69c" stroke-width="13" pathLength="100" stroke-dasharray="39 61" stroke-dashoffset="-61"/>
      <text x="15" y="156" fill="#8998ad" font-size="11">0</text><text x="15" y="90" fill="#8998ad" font-size="11">20</text><text x="109" y="18" fill="#8998ad" font-size="11">50</text><text x="156" y="25" fill="#8998ad" font-size="11">60</text><text x="211" y="156" fill="#8998ad" font-size="11">100</text>
      <path d="M120 133 L${x.toFixed(1)} ${y.toFixed(1)}" stroke="#ecf2fa" stroke-width="4" stroke-linecap="round"/><circle cx="120" cy="133" r="6" fill="#ecf2fa"/>
      </svg>`;
    $('gaugeValue').innerHTML=label;$('gaugeCaption').textContent=caption;
  }
  function renderHero(){
    const freshCount=Object.values(asset.metrics).filter(m=>M.fresh(m)).length;
    $('coverage').textContent=`${freshCount} / ${Object.keys(asset.metrics).length}`;
    $('snapshotTime').textContent=date(data.generatedAt,true)+' 北京时间';
    const s=M.score(asset),comb=isBTC?M.combination(asset.metrics):null;
    let title,explainer;
    if(isBTC){
      drawGauge(s.lower,`${fmt(s.lower,1)}<span>${s.upper!==s.lower?'–'+fmt(s.upper,1):' /100'}</span>`,s.upper!==s.lower?'观察分数区间 · 非确定分值':'公开数据观察分数');
      title=comb===true?'组合条件已满足':comb===false?'组合条件尚未满足':'组合条件待确认';
      explainer=`必要信号 ${counts(asset.groups[0]).active}/${asset.groups[0].items.length} 亮起；组合条件需同时低于 STH 成本、距 90 天高点回撤至少 20%。${s.available<s.total?'缺失或过期项使分数仍有不确定性。':'请结合来源与市场背景观察。'}`;
      $('heroBadges').innerHTML=`<span class="status-chip">有效条件<b>${s.available}/${s.total}</b></span><span class="status-chip">缺失／过期<b>${s.total-s.available}</b></span>`;
    }else{
      const c=counts(asset.groups[0]);
      drawGauge(c.active/4*100,`${c.active}<span> / 4</span>`,'已满足的技术观察条件');
      const m=asset.metrics.mayer;
      title=M.fresh(m)?(m.value<1?'价格位于 200 日均线下方':'价格位于 200 日均线上方'):'ETH 技术状态待确认';
      explainer='独立观察价格周期、供给质押和网络流动性。ETH 不套用 BTC 的矿工指标、STH 成本或综合分数。';
      $('heroBadges').innerHTML=`<span class="status-chip">技术数据<b>${c.known}/4</b></span><span class="status-chip">协议数据<b>${freshCount}/${Object.keys(asset.metrics).length}</b></span>`;
    }
    $('heroTitle').textContent=title;$('heroExplainer').textContent=explainer;
    $('heroFooter').textContent='绿色表示观察条件满足；分数和条件均不是交易指令。';
    $('metricCaption').textContent=isBTC?'三组条件交叉观察，点击指标查看阈值、日期与来源':'技术观察与协议事实分开阅读，点击指标查看数据来源';
    const stale=Object.values(asset.metrics).filter(m=>m.value!=null&&!M.fresh(m)).length;
    const total=Object.keys(asset.metrics).length;
    notice(freshCount<total?`<strong>数据说明</strong>　${freshCount}/${total} 项数据有效，${stale} 项保留了过期读数；其余项暂无可核验数据。缺失、过期均不计为未触发。`:'');
  }
  function counts(group){
    const states=group.items.map(i=>M.signal(i,asset.metrics));
    return {active:states.filter(v=>v===true).length,known:group.items.filter(i=>M.fresh(asset.metrics[i.key])).length};
  }
  function renderGroups(){
    $('signalGroups').innerHTML=asset.groups.map((group,index)=>{
      const c=counts(group),hasRules=group.items.some(i=>i.op);
      const items=group.items.filter(i=>filter==='all'||filter==='triggered'&&M.signal(i,asset.metrics)===true||filter==='missing'&&!M.fresh(asset.metrics[i.key]));
      return `<section class="panel signal-group" aria-labelledby="group-${index}"><div class="group-title"><div class="group-title-left"><h3 id="group-${index}">${esc(group.title)}</h3><span class="group-count">${hasRules?`${c.active}<small> / ${group.items.length} 亮</small>`:`${c.known}<small> / ${group.items.length} 有效</small>`}</span><span class="group-description">${esc(group.description)}</span></div><span class="group-weight">${group.weight?`${group.weight} 分`:'独立观察'}</span></div>
      <div class="metric-grid ${group.items.length===5?'five':''}">${items.length?items.map(item=>{
        const m=asset.metrics[item.key],state=M.signal(item,asset.metrics),ok=M.fresh(m),status=metricStatus(m);
        const threshold=item.op?`目标 ${item.op.replace('<=','≤').replace('>=','≥')} ${item.threshold}${item.unit}`:'供给 / 网络事实';
        const note=state===true?'✓ 已触发':!ok?(m?.value!=null?'过期 · 不参与确认':'暂无可核验数据'):threshold;
        return `<button type="button" class="metric-card ${state===true?'is-triggered':!ok?'is-unavailable':''}" data-metric="${esc(item.key)}" data-group="${index}" aria-label="${esc(item.label)}，${esc(status)}，查看详情"><span class="metric-label"><span class="state-dot"></span>${esc(item.label)}</span><span class="metric-value">${esc(valueText(item.key,m))}${item.unit&&m?.value!=null?`<small>${esc(item.unit)}</small>`:''}</span><span class="metric-threshold">${esc(note)}</span><span class="metric-caption">${esc(m?.source||'来源待补全')}${m?.asOf?' · '+esc(date(m.asOf)):''}</span></button>`;
      }).join(''):'<p class="empty-filter">该组没有符合当前筛选条件的指标。</p>'}</div></section>`;
    }).join('');
    $('signalGroups').querySelectorAll('[data-metric]').forEach(b=>b.addEventListener('click',()=>metricDetail(asset.groups[+b.dataset.group].items.find(i=>i.key===b.dataset.metric))));
  }
  function renderQuote(){
    const m=asset.metrics.price;
    $('price').textContent=money(lastQuote?.price??m.value);
    $('priceType').textContent=lastQuote?'实时参考价':'最近完整日收盘';
    $('quoteSource').textContent=lastQuote?.source||m.source||'暂无来源';
    $('quoteTime').textContent=date(lastQuote?.asOf||m.asOf,!!lastQuote);
    $('priceChange').innerHTML=lastQuote&&typeof lastQuote.change24h==='number'?`<span class="${lastQuote.change24h>=0?'positive':'negative'}">${lastQuote.change24h>0?'+':''}${fmt(lastQuote.change24h,2)}%</span><small>24h</small>`:`<small>${M.fresh(m)?'日线已更新':'日线待更新'}</small>`;
    $('quotePair').textContent=lastQuote?.source==='Coinbase'?symbol+'/USD':symbol+'/USDT';
  }
  function renderPosition(){
    const m=asset.metrics,line=isBTC?M.bullLine(m):M.fresh(m.ma200d)?m.ma200d.value:null;
    $('positionTitle').textContent=isBTC?'定投位置参考':'ETH 均线位置参考';
    $('positionNote').textContent=isBTC?'参考线 = max(200周均线, STH成本) · 仅观察价格位置':'参考线 = ETH 200日均线 · ETH 独立技术观察';
    $('positionTrack').innerHTML=(isBTC?['低于200周线','周线至参考线','线上不足28日','线上至少28日']:['深度折价区','折价观察区','均线附近','均线上方']).map(t=>`<div class="position-segment">${t}</div>`).join('');
    $('bandLine').textContent=`${isBTC?'完整参考线':'200日均线'} ${line?money(line):'待确认'}`;
    $('bandPrice').textContent=`日收盘 ${money(m.price.value)}`;
    $('bandUnknown').textContent=isBTC?(line?'参考线有效；缺少完整 STH 历史，线上连续 28 日状态暂不推断。':'STH 成本缺失或过期，完整位置带待确认；不以其他成本代替。'):'仅显示当前 ETH 日收盘与均线关系，不构成执行指令。';
    if(isBTC){const idx=M.positionBand(m);if(idx!==null)$('positionTrack').children[idx].classList.add('active');}
    if(line&&M.fresh(m.price)&&!isBTC){
      const ratio=m.price.value/line,idx=ratio<.8?0:ratio<1?1:ratio<1.05?2:3;
      $('positionTrack').children[idx].classList.add('active');
      $('bandUnknown').textContent+=' 区间边界为均线的 0.8、1.0、1.05 倍。';
    }
  }
  function renderChart(){
    const points=M.rangeHistory(asset.history||[],range),box=$('priceChart');
    $('chartPeriod').textContent=`近 ${range} 天`;
    if(points.length<2){box.innerHTML='<div class="chart-empty">暂无可核验的价格历史，未绘制示意走势。</div>';return;}
    const W=Math.max(290,Math.min(860,box.clientWidth)),H=250,L=W<500?48:59,R=20,T=20,B=35,values=points.flatMap(p=>[p.close,p.ma200].filter(v=>typeof v==='number'&&v>0));
    const low=Math.min(...values)*.96,high=Math.max(...values)*1.04;
    const x=i=>L+i/(points.length-1)*(W-L-R),y=v=>T+(high-v)/(high-low)*(H-T-B);
    const line=key=>points.map((p,i)=>p[key]!=null?`${i===0||points[i-1][key]==null?'M':'L'}${x(i).toFixed(2)} ${y(p[key]).toFixed(2)}`:'').join(' ');
    let grid='';for(let i=0;i<4;i++){const val=low+(high-low)*i/3,yy=y(val);grid+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#2b3542" stroke-dasharray="3 5"/><text x="${L-12}" y="${yy+4}" text-anchor="end" fill="#8c9aaf" font-size="11">${esc(money(val,true))}</text>`;}
    for(let i=0;i<5;i++){const idx=Math.round((points.length-1)*i/4);grid+=`<text x="${x(idx)}" y="${H-9}" text-anchor="middle" fill="#8c9aaf" font-size="11">${esc(date(points[idx].date))}</text>`;}
    const last=points.at(-1),path=line('close');
    box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(symbol)} 近 ${range} 天日收盘与200日均线，${esc(points[0].date)} 至 ${esc(last.date)}"><defs><linearGradient id="price-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ffb547" stop-opacity=".16"/><stop offset="100%" stop-color="#ffb547" stop-opacity="0"/></linearGradient></defs>${grid}<path d="${path} L${x(points.length-1)} ${H-B} L${L} ${H-B} Z" fill="url(#price-fill)"/><path d="${line('ma200')}" fill="none" stroke="#70aaff" stroke-width="1.7" stroke-dasharray="5 4"/><path d="${path}" fill="none" stroke="#ffb547" stroke-width="2.3" stroke-linejoin="round"/><circle cx="${x(points.length-1)}" cy="${y(last.close)}" r="4" fill="#ffb547" stroke="#151c26" stroke-width="2"/><line id="chartCrosshair" x1="${L}" x2="${L}" y1="${T}" y2="${H-B}" stroke="#a6b5c8" stroke-dasharray="3 3" visibility="hidden"/><rect id="chartHit" x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}" fill="transparent"/></svg><div class="chart-tip" id="chartTip" hidden></div>`;
    const hit=$('chartHit'),tip=$('chartTip');
    hit.addEventListener('pointermove',e=>{
      const svg=box.querySelector('svg'),b=svg.getBoundingClientRect(),vx=(e.clientX-b.left)/b.width*W;
      const idx=Math.max(0,Math.min(points.length-1,Math.round((vx-L)/(W-L-R)*(points.length-1))));
      const p=points[idx];tip.textContent=p.date+'　'+money(p.close);tip.hidden=false;
      tip.style.left=Math.min(box.clientWidth-180,Math.max(12,e.clientX-box.getBoundingClientRect().left-80))+'px';
      $('chartCrosshair').setAttribute('x1',x(idx));$('chartCrosshair').setAttribute('x2',x(idx));$('chartCrosshair').setAttribute('visibility','visible');
    });
    hit.addEventListener('pointerleave',()=>{tip.hidden=true;$('chartCrosshair').setAttribute('visibility','hidden');});
    $('chartSource').textContent=`Binance · 完整 UTC 日线 · ${points.length} 个观测值`;
    $('chartDate').textContent='截至 '+last.date;
  }
  function renderMiniStats(){
    const m=asset.metrics,stats=[['90 天收盘高点','high90'],['距高点回撤','drawdown90'],['200 日均线','ma200d']];
    $('miniStats').innerHTML=stats.map(([label,key])=>`<div class="mini-stat"><div class="mini-stat-label">${label}</div><div class="mini-stat-value ${key==='drawdown90'?'amber':''}">${key==='drawdown90'?fmt(m[key].value,1)+(m[key].value!=null?'%':''):money(m[key].value,true)}</div><div class="mini-stat-note">${esc(metricStatus(m[key]))} · ${esc(date(m[key].asOf))}</div></div>`).join('');
  }
  function renderLadder(){
    const m=asset.metrics,entries=[['最近日收盘','price'],['200 日均线','ma200d'],['200 周均线','ma200w']];
    if(isBTC)entries.splice(2,0,['True Mean 成本','true_mean'],['LTH 实现成本','lth_cost'],['短期持有者成本','sth_cost'],['实现价格','realized_price']);
    $('priceLadder').innerHTML=entries.map(([label,key],i)=>{
      const entry=m[key],ok=M.fresh(entry),delta=ok&&M.fresh(m.price)?(entry.value/m.price.value-1)*100:null;
      return `<div class="ladder-row"><span class="ladder-label"><span class="state-dot" style="background:${i===0?'var(--blue)':ok?'var(--green)':'#576276'}"></span>${label}</span><strong class="${ok?'':'muted'}">${money(entry?.value)}</strong><div class="ladder-meta"><span>${esc(entry?.source||'暂无来源')} · ${esc(date(entry?.asOf))}</span><span>${!ok?esc(metricStatus(entry)):delta!=null?(delta>0?'+':'')+fmt(delta,1)+'%':''}</span></div></div>`;
    }).join('');
  }
  function renderSentiment(){
    const m=asset.metrics,entries=isBTC?[['恐慌 · Alternative.me','fear',''],['恐慌 · CMC','cmc_fear',''],['最新资金费率','funding','%'],['合约多空人数比','long_short',''],['25Δ 风险逆转','risk_reversal25',''],['DVOL 隐含波动率','dvol','']]:[['最新资金费率','funding','%'],['合约多空人数比','long_short',''],['DVOL 隐含波动率','dvol',''],['25Δ 风险逆转','risk_reversal25',''],['周线 RSI','weekly_rsi',''],['ETH Mayer 倍数','mayer','']];
    $('sentimentGrid').innerHTML=entries.map(([label,key,unit])=>{
      const mm=m[key];return `<div class="sentiment-item"><span>${label}</span><strong class="${M.fresh(mm)?'':'muted'}">${esc(valueText(key,mm))}${mm?.value!=null?unit:''}</strong><small>${mm?.sourceUrl?`<a href="${esc(mm.sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(mm.source)}</a>`:'来源待补全'} · ${esc(metricStatus(mm))}</small><small>${esc(date(mm?.asOf,true))}</small></div>`;
    }).join('');
  }
  function renderFlow(legacy){
    const current=asset.etf;
    if(current?.rows?.length){
      const rows=current.rows.slice(-5),sum=rows.reduce((s,r)=>s+r.value,0);
      const age=(Date.now()-Date.parse(current.asOf))/86400000,valid=Number.isFinite(age)&&age>=0&&age<=7;
      $('flowValue').textContent=(sum>=0?'+':'−')+'$'+short(Math.abs(sum)*1e6);
      $('flowValue').className='flow-number '+(valid?(sum>=0?'positive':'negative'):'muted');
      $('flowSubtitle').textContent=`${symbol} ETF · ${rows.length} 个交易日合计 · ${valid?'有效':'已过期'}`;
      const max=Math.max(1,...rows.map(r=>Math.abs(r.value)));
      $('flowChart').hidden=false;$('flowDates').hidden=false;
      $('flowChart').innerHTML=rows.map(r=>`<div class="flow-bar-wrap" title="${esc(r.date)}: ${esc(fmt(r.value,1))} 百万美元"><span class="flow-bar ${r.value<0?'negative':''}" style="height:${Math.abs(r.value)/max*45}%;${r.value>=0?'bottom':'top'}:50%"></span></div>`).join('');
      $('flowDates').innerHTML=rows.map(r=>`<span>${esc(date(r.date))}</span>`).join('');
      $('flowNote').innerHTML=`<a href="${esc(current.sourceUrl)}" target="_blank" rel="noopener noreferrer">Farside Investors ↗</a> · 截至 ${esc(current.asOf)}。${valid?'部分日数据可能继续修订。':'旧值仅作历史记录，不代表当日资金流。'}`;
      return;
    }
    const etf=isBTC?legacy?.etf:null;
    // Existing legacy days have no individually verified dates. Do not invent labels/history.
    const stamp=etf?.latest_date;
    const rawDate=Date.parse(stamp),valid=typeof etf?.sum5d==='number'&&Number.isFinite(rawDate);
    const status=valid&&Date.now()-rawDate<=7*86400000&&Date.now()>=rawDate?'有效':'已过期';
    $('flowValue').textContent=valid?(etf.sum5d>0?'+':'−')+'$'+short(Math.abs(etf.sum5d)*1e6):'—';
    $('flowValue').className='flow-number '+(valid?(etf.sum5d>=0?'positive':'negative'):'muted');
    $('flowSubtitle').textContent=isBTC?`ETF 近 5 个交易日净流入 · ${valid?status:'暂无可核验数据'}`:'ETH ETF：暂无独立数据，未套用 BTC 流量';
    $('flowChart').hidden=true;$('flowDates').hidden=true;
    $('flowNote').textContent=valid?`Farside · 截至 ${stamp}。旧值仅作历史记录，不作为当日资金流。`:'未绘制估计资金流柱状图；公开数据接通后按实际交易日展示。';
  }
  function renderReserves(){
    const rows=reserves?.assets?.[symbol]?.exchanges;
    if(!Array.isArray(rows)||!rows.length){$('reserveList').innerHTML='<p class="side-note">暂无可核验的交易所储备数据。</p>';return;}
    const age=(Date.now()-Date.parse(reserves.anchor))/3600000,ok=age>=0&&age<=60;
    $('reserveDate').textContent=date(reserves.anchor)+(ok?'':' · 已过期');
    $('reserveList').innerHTML=[...rows].sort((a,b)=>b.latest-a.latest).slice(0,5).map(row=>{
      const v=row.change?.[reserveWindow],fresh=M.reserveFresh(reserves.anchor,row);
      return `<div class="reserve-row"><div><strong>${esc(row.name)}</strong><span>${esc(short(row.latest))} ${symbol}</span></div><div class="${fresh&&typeof v==='number'?(v>=0?'positive':'negative'):'muted'}">${typeof v==='number'?(v>0?'+':'')+esc(short(v)):'—'}<small>${fresh?'储备变化':'历史记录'}</small></div></div>`;
    }).join('');
    $('reserveNote').textContent=`DefiLlama 公开地址口径 · ${symbol==='ETH'?'ETH 包含指定 L2 原生/封装 ETH；':''}储备变化剔除单日超过20%的异常台阶，不等同于交易净流入，更不等同于巨鲸净买入。`;
  }
  function render(){
    renderHero();renderQuote();renderPosition();renderGroups();renderChart();renderMiniStats();renderLadder();renderSentiment();
  }
  async function loadQuote(){
    try{
      const r=await fetch(`/api/ticker?symbol=${symbol}`,{signal:AbortSignal.timeout(8000)});
      if(!r.ok)throw Error('quote');const q=await r.json();
      if(typeof q.price!=='number'||!Number.isFinite(q.price)||q.price<=0||!q.asOf||!M.fresh({value:q.price,asOf:q.asOf,maxAgeHours:.05}))throw Error('invalid quote');
      lastQuote=q;
    }catch{lastQuote=null;}
    if(asset)renderQuote();
  }
  async function load(){
    $('refresh').disabled=true;
    try{
      const r=await fetch('/data/observatory.json',{cache:'no-store',signal:AbortSignal.timeout(12000)});
      if(!r.ok)throw Error('snapshot');const next=await r.json();
      if(!next.assets?.[symbol]?.metrics||!Array.isArray(next.assets[symbol].groups))throw Error('schema');
      data=next;asset=data.assets[symbol];render();
      renderFlow(null);
      try{const res=await fetch(isBTC?'/data.json':'/eth-data.json',{signal:AbortSignal.timeout(5000)});if(res.ok)renderFlow(await res.json());else renderFlow(null);}catch{renderFlow(null);}
      try{const res=await fetch('/data/cex-reserves.json',{signal:AbortSignal.timeout(6000)});if(res.ok)reserves=await res.json();}catch{}
      renderReserves();
      await loadQuote();
    }catch{
      if(asset){render();notice('<strong>更新未成功</strong>　保留上次已加载的快照，日期与过期状态仍按实际时间计算。');}
      else{notice('<strong>暂时无法读取数据</strong>　请稍后点击刷新。当前没有生成观察结论，也没有使用参考图数值代替。');$('heroTitle').textContent='等待有效数据';$('heroExplainer').textContent='公开数据快照暂不可用，页面不会把缺失值当作零分。';$('snapshotTime').textContent='快照读取失败';}
    }finally{$('refresh').disabled=false;}
  }
  $('refresh').addEventListener('click',load);
  document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));if(asset)renderGroups();}));
  document.querySelectorAll('[data-range]').forEach(b=>b.addEventListener('click',()=>{range=+b.dataset.range;document.querySelectorAll('[data-range]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));if(asset)renderChart();}));
  document.querySelectorAll('[data-reserve-window]').forEach(b=>b.addEventListener('click',()=>{reserveWindow=b.dataset.reserveWindow;document.querySelectorAll('[data-reserve-window]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderReserves();}));
  document.querySelectorAll('[data-method]').forEach(b=>b.addEventListener('click',()=>showDialog('指标口径与计算方法',methodHTML)));
  $('sourcesButton').addEventListener('click',()=>showDialog('数据来源与更新时间',`<p>每个指标卡片均可查看原始日期和来源。页面刷新只重新读取快照，不会更改源数据的观测日期。</p><h3>本面板使用的公开来源</h3><div class="source-list">${(data?.sources||[]).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)} <span class="muted">↗</span></a>`).join('')||'<p>快照未加载，可稍后重试。</p>'}</div><h3>更新节奏</h3><p>行情约 30 秒刷新；研究快照约每6小时生成，链上源缓存24小时。免费链上数据可能延迟，具体以指标卡片日期为准。实体资金流暂无来源时保持缺失。</p>`));
  $('closeDialog').addEventListener('click',()=>$('infoDialog').close());
  $('infoDialog').addEventListener('click',e=>{if(e.target===$('infoDialog')){const r=$('infoDialog').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('infoDialog').close();}});
  setInterval(()=>{if(!document.hidden&&asset){render();loadQuote();}},30000);
  load();
})();
