(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.FlowModel=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const DAY=86400000;
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const OPS={'<':(x,t)=>x<t,'<=':(x,t)=>x<=t,'>':(x,t)=>x>t,'>=':(x,t)=>x>=t};
  // Snapshot metrics carry an hour budget; signal items carry a day budget against the UTC date.
  function fresh(m,now=Date.now()){
    if(!m||!finite(m.value)||!m.asOf)return false;
    const t=Date.parse(m.asOf);if(!Number.isFinite(t))return false;
    const age=(now-t)/3600000;
    return age>=-0.1&&age<=(m.maxAgeHours??72);
  }
  function utcDay(now){return Date.UTC(new Date(now).getUTCFullYear(),new Date(now).getUTCMonth(),new Date(now).getUTCDate());}
  function itemFresh(item,now=Date.now()){
    if(!item||!finite(item.value)||!item.asOf)return false;
    const t=Date.parse(item.asOf.slice(0,10)+'T00:00:00Z');if(!Number.isFinite(t))return false;
    const days=(utcDay(now)-t)/DAY;
    return days>=0&&days<=(item.maxAgeDays??3);
  }
  function itemState(item,now=Date.now()){
    if(!itemFresh(item,now)||!OPS[item.op])return null;
    return OPS[item.op](item.value,item.threshold);
  }
  function score(groups,now=Date.now()){
    let lower=0,upper=0,lit=0,known=0,total=0;const per=[];
    for(const g of groups||[]){
      const w=g.weight?g.weight/g.items.length:0;let gl=0,gk=0;
      for(const item of g.items){
        total++;const s=itemState(item,now);
        if(s!==null){known++;gk++;}
        if(s===true){lit++;gl++;lower+=w;}
        if(s!==false)upper+=w;
      }
      per.push({id:g.id,lit:gl,known:gk,total:g.items.length});
    }
    return {lower:+lower.toFixed(1),upper:+upper.toFixed(1),lit,known,total,groups:per};
  }
  const BANDS=[[60,'strong','历史低位信号集中'],[50,'building','低位信号增强'],[20,'watch','进入关注区'],[0,'none','无底部信号']];
  function verdict(value){for(const [floor,code,label] of BANDS)if(value>=floor)return {code,label,floor};return {code:'none',label:'无底部信号',floor:0};}
  // Percent move from the reference price to the trigger price (negative = needs to fall).
  function move(target,price){return finite(target)&&finite(price)&&price>0?(target/price-1)*100:null;}
  function triggerPrice(item){return item?.gap&&finite(item.gap.triggerPrice)?item.gap.triggerPrice:null;}
  function comboState(combo,price){
    if(!combo||!finite(price))return null;
    const t=combo.conditions.map(c=>c.triggerPrice);
    if(!t.every(finite))return null;
    return {each:t.map(x=>price<(x)),all:t.every(x=>price<x),target:Math.min(...t)};
  }
  function rangeHistory(history,days){
    const rows=(history||[]).filter(p=>finite(p?.close)&&p.close>0&&Number.isFinite(Date.parse(p.date)));
    if(!rows.length)return [];
    const end=Date.parse(rows.at(-1).date);
    return rows.filter(p=>end-Date.parse(p.date)<(days)*DAY);
  }
  function reserveFresh(anchor,row,now=Date.now()){
    const a=Date.parse(anchor),r=Date.parse(row?.asOf);
    return Number.isFinite(a)&&Number.isFinite(r)&&now-a<=60*3600000&&a-r<=36*3600000&&r<=now;
  }
  return {fresh,itemFresh,itemState,score,verdict,move,triggerPrice,comboState,rangeHistory,reserveFresh,BANDS};
});
