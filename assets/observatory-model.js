(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.FlowModel=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function fresh(m,now=Date.now()){
    if(!m||typeof m.value!=='number'||!Number.isFinite(m.value)||!m.asOf)return false;
    const age=(now-Date.parse(m.asOf))/3600000;
    return Number.isFinite(age)&&age>=0&&age<=(m.maxAgeHours??72)&&m.status!=='missing'&&
      (!m.dependencies||Object.values(m.dependencies).every(d=>fresh({...d,value:1},now)));
  }
  function signal(item,metrics,now=Date.now()){
    const m=metrics[item.key];
    if(!item.op||!fresh(m,now))return null;
    const v=m.value,t=item.threshold;
    return item.op==='<'?v<t:item.op==='<='?v<=t:item.op==='>'?v>t:item.op==='>='?v>=t:null;
  }
  function score(asset,now=Date.now()){
    if(asset.symbol==='ETH')return null;
    let lower=0,upper=0,available=0,total=0;
    for(const group of asset.groups){
      const weight=group.weight/group.items.length;
      for(const item of group.items){
        const state=signal(item,asset.metrics,now);
        total++;
        if(state!==null)available++;
        if(state===true)lower+=weight;
        if(state!==false)upper+=weight;
      }
    }
    return {lower:+lower.toFixed(1),upper:+upper.toFixed(1),available,total};
  }
  function bullLine(metrics,now=Date.now()){
    if(!fresh(metrics.ma200w,now)||!fresh(metrics.sth_cost,now))return null;
    return Math.max(metrics.ma200w.value,metrics.sth_cost.value);
  }
  function combination(metrics,now=Date.now()){
    const values=[fresh(metrics.price,now)&&fresh(metrics.sth_cost,now)?metrics.price.value<metrics.sth_cost.value:null,
      fresh(metrics.drawdown90,now)?metrics.drawdown90.value>=20:null];
    return values.includes(false)?false:values.includes(null)?null:true;
  }
  function reserveFresh(anchor,row,now=Date.now()){
    return !row.stale&&fresh({value:1,asOf:anchor,maxAgeHours:60},now)&&fresh({value:1,asOf:row.asOf,maxAgeHours:60},now);
  }
  function positionBand(metrics,now=Date.now()){
    const line=bullLine(metrics,now);
    if(!line||!fresh(metrics.price,now))return null;
    if(metrics.price.value<=metrics.ma200w.value)return 0;
    return metrics.price.value<line?1:null;
  }
  function rangeHistory(points,days){
    if(!points.length)return [];
    const cutoff=Date.parse(points.at(-1).date)-(days-1)*86400000;
    return points.filter(p=>Date.parse(p.date)>=cutoff&&Number.isFinite(p.close)&&p.close>0);
  }
  return {fresh,signal,score,bullLine,combination,rangeHistory,reserveFresh,positionBand};
});
