(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.FlowModel=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const DAY=86400000;
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  // Prototype-free so inherited names such as "toString" can never act as an operator.
  const OPS=Object.assign(Object.create(null),{'<':(x,t)=>x<t,'<=':(x,t)=>x<=t,'>':(x,t)=>x>t,'>=':(x,t)=>x>=t});
  // Snapshot metrics carry an hour budget; signal items carry a day budget against the UTC date.
  function fresh(m,now=Date.now()){
    if(!m||!finite(m.value)||!m.asOf)return false;
    const t=Date.parse(m.asOf);if(!Number.isFinite(t))return false;
    const age=(now-t)/3600000;
    return age>=-0.1&&age<=(m.maxAgeHours??72);
  }
  function utcDay(now){return Date.UTC(new Date(now).getUTCFullYear(),new Date(now).getUTCMonth(),new Date(now).getUTCDate());}
  // A real calendar day as epoch ms, or NaN: "2026-02-30" must not roll over into March.
  function calendarDay(asOf){
    if(typeof asOf!=='string'||!/^\d{4}-\d{2}-\d{2}/.test(asOf))return NaN;
    const day=asOf.slice(0,10),t=Date.parse(day+'T00:00:00Z');
    return Number.isFinite(t)&&new Date(t).toISOString().slice(0,10)===day?t:NaN;
  }
  function itemFresh(item,now=Date.now()){
    if(!item||!finite(item.value))return false;
    const t=calendarDay(item.asOf);if(!Number.isFinite(t))return false;
    const days=(utcDay(now)-t)/DAY;
    return days>=0&&days<=(item.maxAgeDays??3);
  }
  function itemState(item,now=Date.now()){
    if(!itemFresh(item,now)||!item.op||!(item.op in OPS)||!finite(item.threshold))return null;
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
  // Each condition carries its own observation date: STH cost lives 4 days, the 90-day high 3.
  // ① price < STH cost (strict); ② drawdown >= 20% means price <= 0.8 x high (inclusive).
  const COMBO={sth:{age:4,met:(p,t)=>p<t},drawdown:{age:3,met:(p,t)=>p<=t}};
  function comboState(combo,price,now=Date.now()){
    const c=combo?.conditions;
    if(!finite(price)||!Array.isArray(c)||c.length!==2||c[0]?.id!=='sth'||c[1]?.id!=='drawdown')return null;
    const ok=c.every(x=>finite(x.triggerPrice)&&x.triggerPrice>0&&itemFresh({value:x.triggerPrice,asOf:x.asOf,maxAgeDays:COMBO[x.id].age},now));
    if(!ok)return null;
    const each=c.map(x=>COMBO[x.id].met(price,x.triggerPrice));
    return {each,all:each.every(Boolean),target:Math.min(...c.map(x=>x.triggerPrice))};
  }
  function dayFresh(asOf,maxDays,now=Date.now()){return itemFresh({value:0,asOf,maxAgeDays:maxDays},now);}
  function reserveFresh(anchor,row,now=Date.now()){
    const a=Date.parse(anchor),r=Date.parse(row?.asOf);
    return Number.isFinite(a)&&Number.isFinite(r)&&a<=now&&now-a<=60*3600000&&a-r<=36*3600000&&r<=now;
  }
  return {fresh,itemFresh,itemState,score,verdict,move,triggerPrice,comboState,dayFresh,reserveFresh,BANDS};
});
