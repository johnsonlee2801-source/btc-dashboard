(() => {
  'use strict';
  const M=window.PositioningRadarModel;
  const full=document.body.hasAttribute('data-radar-page');
  const summaries=[...document.querySelectorAll('[data-radar-summary]')];
  if(!M||(!full&&!summaries.length))return;
  let snapshot=null,analysis=null,loadError=false,busy=false,query='',filter='all';
  const expanded=new Set(),sorts=new Map();
  const labels={topLong:'大户持仓多头占比',accountLong:'全体账户多头占比',topDelta:'大户多头占比24h变化',accountDelta:'全体账户多头占比24h变化',oiUsd:'未平仓名义金额 OI',oiUnits:'未平仓合约标的数量',oiDelta:'OI名义金额24h变化',priceChange:'价格24h变化',volumeUsd:'合约24h成交额',fundingRate:'最近已结算资金费率',fundingHours:'实际结算间隔',concentration:'调整后前10地址集中度',circulation:'流通供应 / 总供应',unlockPct:'未来30天解锁 / 当前流通量',unknownShare:'原始前10未知地址余额占比',lockedShare:'原始前10已验证锁定余额占比'};
  const E=(tag,text,className)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;};
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const date=v=>finite(v)?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(v)+' 北京时间':'暂无观测时间';
  const num=(v,d=1)=>finite(v)?v.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d}):'—';
  const pct=(v,signed=false,d=1)=>finite(v)?(signed&&v>0?'+':'')+num(v,d)+'%':'—';
  function money(v){if(!finite(v))return '—';return '$'+(Math.abs(v)>=1e9?num(v/1e9,2)+'B':Math.abs(v)>=1e6?num(v/1e6,2)+'M':Math.abs(v)>=1e3?num(v/1e3,1)+'K':num(v,0));}
  function tone(v){return !finite(v)?'radar-muted':v>0?'radar-up':v<0?'radar-down':'radar-muted';}
  function sourceLink(url,text){const safe=M.safeUrl(url);if(!safe)return E('span',text,'radar-muted');const a=E('a',text);a.href=safe;a.target='_blank';a.rel='noopener noreferrer';return a;}
  function stat(key,value){for(const el of document.querySelectorAll('[data-radar-stat="'+key+'"]')){el.textContent=value==null?'待核验':String(value);el.classList.toggle('is-unknown',value==null);}}
  function initSummary(host){
    const head=E('div',undefined,'radar-summary-head');head.append(E('h2','资金与持仓雷达'));
    const link=E('a','查看完整多币种榜单 →');link.href='/positioning-radar';head.append(link);
    const grid=E('div',undefined,'radar-summary-grid');
    for(const [key,label] of [['divergence','大户 / 账户方向分歧'],['high','高集中度已核验'],['coverage','持仓有效 / 合约总数']]){
      const box=E('div');const count=E('strong','待核验','is-unknown');count.dataset.radarStat=key;box.append(E('span',label),count);grid.append(box);
    }
    host.replaceChildren(head,grid,E('div','正在核对数据…','radar-summary-lead'),E('p','解锁、地址归属和做市关联独立核验；合约多头不等于机构现货买入。','radar-summary-note'));
  }
  summaries.forEach(initSummary);
  function delta(r,key,parent){
    const m=r.metrics?.[key],p=r.metrics?.[parent];
    return m&&p&&m.asOf===p.asOf&&m.fromAsOf===m.asOf-86400000&&M.fresh(m,key,analysis.now)?m.value:null;
  }
  function coinCell(r){
    const box=E('div');const button=E('button',r.baseAsset||r.symbol,'radar-coin');button.type='button';button.addEventListener('click',()=>detail(r));
    box.append(button,E('small',r.symbol),E('small',r.network||'网络 / 地址待核验'));
    if(r.makers?.length)for(const maker of r.makers){const line=E('small');line.append(sourceLink(maker.url,'做市关联：'+maker.name));box.append(line);}
    return box;
  }
  function position(r,key,deltaKey){
    const v=r.values[key];const box=E('div');
    const long=finite(v)&&v>.5,short=finite(v)&&v<.5;
    const share=(short?1-v:v)*100;
    let precision=1;
    while(finite(v)&&share!==50&&Number(share.toFixed(precision))===50&&precision<6)precision++;
    box.append(E('strong',finite(v)?(long?'多 ':short?'空 ':'中性 ')+pct(share,false,precision):'—','radar-primary '+(long?'radar-up':short?'radar-down':'radar-muted')));
    const d=delta(r,deltaKey,key);box.append(E('small',finite(d)?'多头24h '+(d>0?'+':'')+num(d)+'pp':'24h变化待核验'));
    return box;
  }
  function valueCell(r,key){
    const v=r.values[key],box=E('div');
    if(key==='topLong')return position(r,key,'topDelta');
    if(key==='accountLong')return position(r,key,'accountDelta');
    if(key==='oiUsd'){box.append(E('strong',money(v)),E('small',finite(delta(r,'oiDelta','oiUsd'))?pct(delta(r,'oiDelta','oiUsd'),true)+' / 24h':'24h变化待核验'));return box;}
    if(key==='fundingRate'){
      box.append(E('strong',pct(v,true,3),tone(v)),E('small',finite(r.values.fundingHours)?num(r.values.fundingHours,0)+'h · 最近已结算':'结算周期待核验'));return box;
    }
    if(key==='risks'){for(const label of r.risks)box.append(E('span',label,'radar-tag'+(label.includes('待核验')?'':' known')));return box;}
    if(key==='concentrationDelta')return E('span',finite(v)?(v>0?'+':'')+num(v)+'pp':'—',tone(v));
    if(key==='gap')return E('strong',finite(r.gap)?num(r.gap)+'pp':'—','radar-amber');
    if(key==='volumeUsd')return E('span',money(v));
    let d=1;
    if(key==='concentration'&&finite(v))for(const limit of [90,95])if(v<limit&&Number(v.toFixed(d))>=limit)d=4;
    return E('span',pct(v,key==='priceChange',d),key==='priceChange'?tone(v):key==='concentration'?'radar-primary radar-amber':!finite(v)?'radar-muted':'');
  }
  const positioning=[['symbol','币种 / 数据口径'],['topLong','大户（持仓）'],['accountLong','全体（账户）'],['oiUsd','OI / 名义金额'],['priceChange','价格 / 24h'],['fundingRate','资金费率'],['risks','风险核验']];
  const concentration=[['symbol','币种 / 做市关联'],['concentration','调整后集中度'],['concentrationDelta','较前日 / pp'],['circulation','流通率'],['priceChange','价格 / 24h'],['fundingRate','资金费率'],['volumeUsd','成交额 / 24h'],['risks','风险核验']];
  const configs=[
    {key:'divergence',title:'大户与全体账户分歧',kicker:'01 / POSITIONING DIVERGENCE',note:'OI ≥ $10M · 方向相反 · 按多头占比之差排序，不是买入推荐',cols:[...positioning.slice(0,3),['gap','分歧幅度'],...positioning.slice(3)],limit:8,coverage:'position'},
    {key:'crowdedLong',title:'全体账户拥挤 · 多头',kicker:'02 / CROWDED LONG',note:'OI ≥ $3M · 按全体账户多头占比排序 · 全体账户包含大户',cols:positioning,limit:4,coverage:'accounts'},
    {key:'crowdedShort',title:'全体账户拥挤 · 空头',kicker:'03 / CROWDED SHORT',note:'OI ≥ $3M · 按全体账户空头占比排序 · 拥挤不代表必然反转',cols:positioning,limit:4,coverage:'accounts'},
    {key:'high',title:'高集中度 ≥95%',kicker:'04 / CONCENTRATION',note:'调整后前10地址占比 · 排除已验证托管等余额后计算 · 地址不等于实体',cols:concentration,limit:10,coverage:'concentration'},
    {key:'watch',title:'90–95% 观察',kicker:'05 / WATCHLIST',note:'90% ≤ 调整后集中度 < 95% · 与高集中度榜采用相同口径',cols:concentration,limit:10,coverage:'concentration'},
    {key:'cross',title:'高集中度币的多空',kicker:'06 / CROSS CHECK',note:'调整后集中度 ≥95% 且 OI ≥ $3M · 集中度与持仓缺一不可',cols:[...positioning.slice(0,1),['concentration','调整后集中度'],...positioning.slice(1)],limit:8,coverage:'concentration'},
    {key:'market',title:'全部合约 · 数据核验',kicker:'08 / MARKET COVERAGE',note:'点击币种核验逐项日期与来源 · 点击列名排序 · 缺失值不参与对应榜单',cols:[...positioning.slice(0,5),['volumeUsd','成交额 / 24h'],...positioning.slice(5)],limit:20,coverage:'total'}
  ];
  function tableSection(config){
    const a=analysis;const all=config.key==='market'?a.rows:a.groups[config.key];
    let list=M.select(all,query,filter);
    const sort=sorts.get(config.key);
    if(sort)list=[...list].sort((x,y)=>{
      const vx=sort.key==='gap'?x.gap:x.values[sort.key],vy=sort.key==='gap'?y.gap:y.values[sort.key];
      if(!finite(vx))return finite(vy)?1:0;if(!finite(vy))return -1;return (vy-vx)*sort.direction;
    });
    const section=E('section',undefined,'panel radar-section');section.id='radar-'+config.key;section.dataset.kind=config.key;
    const head=E('div',undefined,'radar-section-head'),intro=E('div');
    intro.append(E('span',config.kicker,'radar-kicker'),E('h2',config.title),E('p',config.note));
    head.append(intro,E('span',list.length+' 行 · 有效 '+a.coverage[config.coverage]+'/'+a.coverage.total,'radar-count'));section.append(head);
    if(!list.length){
      const empty=E('div',undefined,'radar-empty');
      const noCoverage=!a.coverage[config.coverage]||!a.live;
      empty.append(E('strong',noCoverage?'等待可核验数据':'当前筛选下暂无符合条件的合约'));
      empty.append(E('p',config.coverage==='concentration'&&noCoverage?'暂无完整地址归属、锁仓与供应证据。此处不使用截图数字，也不以原始大地址占比冒充调整后集中度。':noCoverage?'缺失、过期或窗口不一致的观测不能进入当前榜单。请查看全部合约的逐项日期。':'可以清除搜索或切换观察条件；当前结果不代表未来方向。'));
      section.append(empty);return section;
    }
    const scroll=E('div',undefined,'radar-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label',config.title+'表格，可横向滚动');
    const table=E('table',undefined,'radar-table');const caption=E('caption',config.title,'sr-only');table.append(caption);
    const headrow=E('tr');for(const [key,label] of config.cols){const th=E('th');th.scope='col';
      if(!['symbol','risks'].includes(key)){const button=E('button',label+(sort?.key===key?(sort.direction===1?' ↓':' ↑'):''),'radar-sort');button.type='button';button.dataset.radarFocus=config.key+':sort:'+key;button.addEventListener('click',()=>{sorts.set(config.key,{key,direction:sort?.key===key?-sort.direction:1});renderSections();});th.append(button);}
      else th.textContent=label;headrow.append(th);
    }
    const thead=E('thead');thead.append(headrow);table.append(thead);const body=E('tbody');
    for(const r of expanded.has(config.key)?list:list.slice(0,config.limit)){const tr=E('tr');for(const [key]of config.cols){const td=E('td');td.append(key==='symbol'?coinCell(r):valueCell(r,key));if(key==='symbol')td.querySelector('button').dataset.radarFocus=config.key+':coin:'+r.symbol;tr.append(td);}body.append(tr);}
    table.append(body);scroll.append(table);section.append(scroll,E('div','左右滑动查看全部指标 · 点击币种查看证据','radar-scroll-hint'));
    if(list.length>config.limit){const button=E('button',expanded.has(config.key)?'收起':'展开全部','radar-expand');button.type='button';button.dataset.radarFocus=config.key+':expand';button.setAttribute('aria-expanded',String(expanded.has(config.key)));button.addEventListener('click',()=>{expanded.has(config.key)?expanded.delete(config.key):expanded.add(config.key);renderSections();});section.append(button);}
    return section;
  }
  function changesSection(){
    const c=analysis.changes;const section=E('section',undefined,'panel radar-section');section.id='radar-changes';
    const head=E('div',undefined,'radar-section-head'),intro=E('div');intro.append(E('span','07 / DAILY CHANGES','radar-kicker'),E('h2','今日变化'),E('p','只比较同币种、同口径且对齐24小时的观测；采集缺口不算退出'));head.append(intro);section.append(head);
    const grid=E('div',undefined,'radar-change-grid');
    for(const [title,list,empty]of [['集中度上升 / 下降',[...c.up,...c.down],'暂无可对齐的集中度历史。'],['高集中度新增 / 退出',[],c.compared?'新增 '+c.entered+' · 退出 '+c.exited+' · 有效比较 '+c.compared+' 个':'待核验：不能把未采集或过期算作退出。'],['持仓方向变化',c.direction,'当前没有已核验的方向切换，或缺少完整24h比较。']]){
      const box=E('div');box.append(E('h3',title));
      if(!list.length)box.append(E('p',empty));
      for(const x of list.slice(0,10)){const line=E('div',x.symbol+' · '+(x.label||(x.delta>0?'+':'')+num(x.delta)+'pp'),'radar-change-line');line.append(E('small',date(x.fromAsOf)+' → '+date(x.asOf)));box.append(line);}grid.append(box);
    }section.append(grid);return section;
  }
  function renderSections(){
    if(!full||!analysis)return;
    const focus=document.activeElement?.dataset?.radarFocus;
    const scrolls=new Map([...document.querySelectorAll('.radar-section .radar-scroll')].map(x=>[x.closest('section').id,x.scrollLeft]));
    const sections=[];for(const config of configs){if(config.key==='market')sections.push(changesSection());sections.push(tableSection(config));}
    document.getElementById('radarSections').replaceChildren(...sections);
    for(const node of document.querySelectorAll('.radar-section .radar-scroll'))node.scrollLeft=scrolls.get(node.closest('section').id)||0;
    if(focus)document.querySelector('[data-radar-focus="'+CSS.escape(focus)+'"]')?.focus({preventScroll:true});
  }
  function detail(r){
    let dialog=document.getElementById('radarDialog');
    if(!dialog){dialog=E('dialog');dialog.id='radarDialog';dialog.setAttribute('aria-labelledby','radarDetailTitle');const header=E('div',undefined,'dialog-header');const title=E('h2');title.id='radarDetailTitle';const close=E('button','×','close-dialog');close.type='button';close.setAttribute('aria-label','关闭币种证据');close.addEventListener('click',()=>dialog.close());header.append(title,close);const content=E('div',undefined,'dialog-content');content.id='radarDetail';dialog.append(header,content);document.body.append(dialog);}
    document.getElementById('radarDetailTitle').textContent=r.symbol+' · 数据证据';
    const content=document.getElementById('radarDetail');content.replaceChildren(E('p','大户：保证金前20%用户的持仓；全体账户：包含大户的账户统计。两者不是独立、互斥的人群。'));
    content.append(E('p','网络：'+(r.network||'待核验')+' · 合约地址：'+(r.address||'待核验')+' · 合约乘数：'+(r.multiplier??'未核验')));
    if(r.makers?.length)for(const maker of r.makers){const p=E('p','做市关联（非当前净买入）：');p.append(sourceLink(maker.url,maker.name),document.createTextNode(' · '+date(maker.asOf)));content.append(p);}
    else content.append(E('p','做市商关联：暂无可引用的已核验归属证据。'));
    const audit=r.concentrationAudit;
    if(audit){
      const part=E('div',undefined,'radar-detail-metric');part.append(E('h3','集中度计算证据'));
      for(const [key,label]of [['totalSupply','原始总供应'],['excludedSupply','剔除余额'],['remainingSupply','剩余供应'],['adjustedTop10Balance','调整后前10余额']])part.append(E('p',label+'：'+num(audit[key],4)));
      part.append(sourceLink(audit.url,'完整原始账本 / 供应证据 ↗'));
      for(const x of audit.excluded||[]){const line=E('p','剔除 '+num(x.amount,4)+' · '+x.kind+' · ');line.append(sourceLink(x.url,x.address));part.append(line);}
      if(audit.omittedExcluded)part.append(E('p','另有 '+audit.omittedExcluded+' 条剔除记录，请查看完整账本。'));
      for(const x of audit.adjustedTop10||[]){const line=E('p','前10合格余额 '+num(x.eligibleBalance,4)+' · ');line.append(sourceLink(x.url,x.address));part.append(line);}
      content.append(part);
    }
    for(const [key,label]of Object.entries(labels)){
      const m=r.metrics?.[key],valid=M.fresh(m,key,Date.now());
      const part=E('div',undefined,'radar-detail-metric');part.append(E('h3',label));
      let text='暂无数据';if(finite(m?.value))text=['oiUsd','volumeUsd'].includes(key)?money(m.value):['topLong','accountLong'].includes(key)?pct(m.value*100):key==='oiUnits'?num(m.value,3):key==='fundingHours'?num(m.value,0)+'h':key.endsWith('Delta')&&key!=='oiDelta'?num(m.value)+'pp':pct(m.value,false,key==='fundingRate'?4:2);
      part.append(E('strong',text),E('p',(valid?'有效观测':finite(m?.value)?'过期或日期无效，不参与当前判断':'待核验')+' · '+date(m?.asOf)));
      if(m?.note)part.append(E('p',m.note));
      if(finite(m?.value)){part.append(sourceLink(m.url,'来源：'+(m.source||'未注明')));if(m.fromAsOf)part.append(E('p','比较起点：'+date(m.fromAsOf)));}
      content.append(part);
    }
    dialog.showModal();
  }
  function render(){
    analysis=M.analyze(snapshot||{},Date.now());const a=analysis;
    stat('divergence',a.counts.divergence);stat('high',a.counts.high);stat('watch',a.counts.watch);stat('coverage',snapshot?a.coverage.position+' / '+a.coverage.total:null);
    const stamps=a.rows.filter(r=>r.positionValid).map(r=>r.metrics.topLong.asOf);
    const observation=stamps.length?'持仓观测 '+date(Math.min(...stamps))+(Math.max(...stamps)!==Math.min(...stamps)?' 至 '+date(Math.max(...stamps)):''):'尚无可对齐的有效持仓';
    let note=loadError?'暂时无法读取雷达快照。可点击刷新重试；不将失败解释为零个机会。':!a.live?'合约清单或快照已过期 / 尚不可用，当前排名暂停，历史字段保留原日期。':'已读取 '+a.coverage.sampled+'/'+a.coverage.total+' 个合约；持仓对齐有效 '+a.coverage.position+'，集中度有效 '+a.coverage.concentration+'。';
    if(snapshot?.partial)note+=' 当前是部分采样，榜单不能代表全市场。';
    if(snapshot?.errors?.length)note+=' '+snapshot.errors.length+' 项源请求失败；保留原日期。最近错误：'+snapshot.errors.slice(0,2).map(e=>[e.symbol,e.source,e.error].filter(Boolean).join(' ')).join('；')+'。';
    if(full){document.getElementById('radarNotice').textContent=note;document.getElementById('radarTime').textContent=observation;renderSections();}
    for(const host of summaries){
      const leaders=a.groups.divergence.slice(0,3).map(r=>(r.baseAsset||r.symbol)+' 分歧 '+num(r.gap)+'pp');
      host.querySelector('.radar-summary-lead').textContent=leaders.length?'方向分歧观察：'+leaders.join(' · '):a.coverage.position?'当前有效样本中暂无满足条件的方向分歧。':'暂无可核验的方向分歧排名。';
      host.querySelector('.radar-summary-note').textContent=note+' '+observation+'。解锁与归属独立核验；合约多头不等于机构买入。';
    }
  }
  async function load(){
    if(busy)return;busy=true;document.querySelectorAll('.radar-refresh').forEach(b=>b.disabled=true);
    try{const response=await fetch('/data/positioning-radar.json',{cache:'no-store',signal:AbortSignal.timeout(15000)});if(!response.ok)throw new Error('HTTP '+response.status);const data=await response.json();if(data.schemaVersion!==1||!Array.isArray(data.rows))throw new Error('Invalid snapshot');snapshot=data;loadError=false;}
    catch{loadError=true;}
    finally{busy=false;render();document.querySelectorAll('.radar-refresh').forEach(b=>b.disabled=false);}
  }
  if(full){
    document.getElementById('radarSearch').addEventListener('input',e=>{query=e.target.value;renderSections();});
    document.getElementById('radarFilter').addEventListener('change',e=>{filter=e.target.value;renderSections();});
    for(const button of document.querySelectorAll('[data-radar-search]'))button.addEventListener('click',()=>{query=button.dataset.radarSearch;document.getElementById('radarSearch').value=query;renderSections();});
    document.getElementById('radarClose').addEventListener('click',()=>document.getElementById('radarDialog').close());
    document.querySelector('.radar-refresh').addEventListener('click',load);
  }
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){render();load();}});
  setInterval(render,60000);setInterval(()=>{if(!document.hidden)load();},300000);
  render();load();
})();
