(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PositioningRadarModel=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const chain=new Set(['concentration','circulation','unlockPct','unknownShare','lockedShare','concentrationDelta']);
  const ratio=new Set(['topLong','accountLong']);
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  function safeUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:null;}catch{return null;}}
  function fresh(m,key,now){
    if(!m||!finite(m.value)||!finite(m.asOf)||m.asOf<=0||m.asOf>now)return false;
    let hours=chain.has(key)?(finite(m.maxAgeHours)?Math.min(72,m.maxAgeHours):48):3;
    if(['fundingRate','fundingHours'].includes(key)&&finite(m.maxAgeHours))hours=Math.min(27,Math.max(3,m.maxAgeHours));
    if(now-m.asOf>hours*3600000)return false;
    if(ratio.has(key)&&(m.value<0||m.value>1))return false;
    if(['concentration','circulation','unknownShare','lockedShare'].includes(key)&&(m.value<0||m.value>100))return false;
    if(['oiUsd','oiUnits','volumeUsd','unlockPct'].includes(key)&&m.value<0)return false;
    return true;
  }
  function value(row,key,now){const m=row?.metrics?.[key];return fresh(m,key,now)?m.value:null;}
  function aligned(row,keys,now){return keys.every(k=>value(row,k,now)!==null)&&new Set(keys.map(k=>row.metrics[k].asOf)).size===1;}
  function analyze(snapshot,now=Date.now()){
    const live=finite(snapshot?.universeAsOf)&&snapshot.universeAsOf<=now&&now-snapshot.universeAsOf<=3*3600000;
    const seen=new Set();const rows=[];
    for(const raw of Array.isArray(snapshot?.rows)?snapshot.rows:[]){
      if(!raw||typeof raw.symbol!=='string'||!raw.symbol||seen.has(raw.symbol))continue;seen.add(raw.symbol);
      const r={...raw,values:{},risks:[]};
      for(const key of Object.keys(raw.metrics||{}))r.values[key]=value(raw,key,now);
      for(const [key,parent] of [['topDelta','topLong'],['accountDelta','accountLong'],['oiDelta','oiUsd']]){
        const d=raw.metrics?.[key],p=raw.metrics?.[parent];
        if(!d||!p||d.asOf!==p.asOf||d.fromAsOf!==d.asOf-86400000)r.values[key]=null;
      }
      const fr=raw.metrics?.fundingRate,fh=raw.metrics?.fundingHours;
      if(r.values.fundingHours!=null&&(!fr||!fh||fr.asOf!==fh.asOf))r.values.fundingHours=null;
      const v=r.values,c=v.concentration;
      r.positionValid=live&&aligned(r,['topLong','accountLong','oiUsd'],now);
      r.accountValid=live&&aligned(r,['accountLong','oiUsd'],now);
      r.chainValid=live&&c!==undefined&&c!==null;
      r.gap=r.positionValid?Math.abs(v.topLong-v.accountLong)*100:null;
      r.divergence=r.positionValid&&v.oiUsd>=10000000&&(v.topLong-.5)*(v.accountLong-.5)<0;
      r.crowdedLong=r.accountValid&&v.oiUsd>=3000000&&v.accountLong>.5;
      r.crowdedShort=r.accountValid&&v.oiUsd>=3000000&&v.accountLong<.5;
      r.high=r.chainValid&&c>=95;r.watch=r.chainValid&&c>=90&&c<95;
      if(v.circulation!=null&&v.circulation<35)r.risks.push('低流通');
      if(v.unlockPct==null)r.risks.push('解锁待核验');else if(v.unlockPct>5)r.risks.push('大额解锁');
      if(v.unknownShare==null)r.risks.push('地址归属待核验');else if(v.unknownShare>50)r.risks.push('未知地址占比高');
      if(v.lockedShare!=null&&v.lockedShare>50)r.risks.push('锁仓为主');
      rows.push(r);
    }
    const sort=(list,get)=>list.sort((a,b)=>get(b)-get(a)||a.symbol.localeCompare(b.symbol));
    const groups={
      divergence:sort(rows.filter(r=>r.divergence),r=>r.gap),
      crowdedLong:sort(rows.filter(r=>r.crowdedLong),r=>r.values.accountLong),
      crowdedShort:sort(rows.filter(r=>r.crowdedShort),r=>1-r.values.accountLong),
      high:sort(rows.filter(r=>r.high),r=>r.values.concentration),
      watch:sort(rows.filter(r=>r.watch),r=>r.values.concentration),
      cross:sort(rows.filter(r=>r.high&&r.positionValid&&r.values.oiUsd>=3000000),r=>r.values.concentration)
    };
    const coverage={position:rows.filter(r=>r.positionValid).length,accounts:rows.filter(r=>r.accountValid).length,concentration:rows.filter(r=>r.chainValid).length,total:finite(snapshot?.universeTotal)?snapshot.universeTotal:rows.length,sampled:rows.length};
    const changes={compared:0,entered:null,exited:null,up:[],down:[],direction:[]};
    for(const r of rows){
      if(r.chainValid){
        const current=r.metrics.concentration;
        // Holder evidence is collected once a day at a drifting time, so "yesterday" is the
        // observation 18-30h earlier closest to 24h, not an exact 86,400,000 ms predecessor.
        let old=null,best=Infinity;
        for(const entry of Array.isArray(snapshot.history)?snapshot.history:[]){
          if(!entry||!Array.isArray(entry.rows))continue;
          const prior=entry.rows.find(x=>x&&x.symbol===r.symbol);
          // A different contract or network is a different measurement, not yesterday's value.
          if(prior?.address&&r.address&&prior.address!==r.address)continue;
          const candidate=prior?.metrics?.concentration;
          const gap=finite(candidate?.asOf)?current.asOf-candidate.asOf:NaN;
          if(gap>=18*3600000&&gap<=30*3600000&&Math.abs(gap-86400000)<best&&fresh(candidate,'concentration',current.asOf)){old=candidate;best=Math.abs(gap-86400000);}
        }
        if(old){
          changes.compared++;changes.entered??=0;changes.exited??=0;
          if(old.value<95&&current.value>=95)changes.entered++;
          if(old.value>=95&&current.value<95)changes.exited++;
          const delta=current.value-old.value;
          r.values.concentrationDelta=delta;
          if(delta!==0)changes[delta>0?'up':'down'].push({symbol:r.symbol,delta,fromAsOf:old.asOf,asOf:current.asOf});
        }
      }
      const td=r.metrics?.topDelta,ad=r.metrics?.accountDelta;
      if(r.positionValid&&fresh(td,'topDelta',now)&&fresh(ad,'accountDelta',now)&&td.asOf===r.metrics.topLong.asOf&&ad.asOf===td.asOf&&td.fromAsOf===td.asOf-86400000&&ad.fromAsOf===td.fromAsOf){
        // Binance publishes shares to 4 decimals; rounding stops 0.58-0.08 reading as 0.4999…
        const round=x=>Math.round(x*1e4)/1e4,side=x=>x>.5?1:x<.5?-1:0;
        const topBefore=round(r.values.topLong-td.value/100),accountBefore=round(r.values.accountLong-ad.value/100);
        if(topBefore>=0&&topBefore<=1&&accountBefore>=0&&accountBefore<=1){
          const was=[side(topBefore),side(accountBefore)],is=[side(r.values.topLong),side(r.values.accountLong)];
          const split=x=>x[0]*x[1]<0;
          if(split(was)!==split(is))changes.direction.push({symbol:r.symbol,label:split(is)?'转为方向分歧':'方向分歧结束',fromAsOf:td.fromAsOf,asOf:td.asOf});
          else if(split(is)&&was[0]!==is[0])changes.direction.push({symbol:r.symbol,label:'分歧方向反转',fromAsOf:td.fromAsOf,asOf:td.asOf});
        }
      }
    }
    changes.up.sort((a,b)=>b.delta-a.delta);changes.down.sort((a,b)=>a.delta-b.delta);
    const counts={divergence:coverage.position?groups.divergence.length:null,high:coverage.concentration?groups.high.length:null,watch:coverage.concentration?groups.watch.length:null};
    return {rows,groups,counts,coverage,changes,live,now};
  }
  function select(rows,query='',filter='all'){
    const q=query.trim().toLowerCase();
    return rows.filter(r=>(!q||[r.symbol,r.baseAsset,r.network].some(x=>String(x||'').toLowerCase().includes(q)))&&
      (filter==='all'||filter==='risk'&&r.risks.length>0||filter==='high'&&r.high||filter==='divergence'&&r.divergence||filter==='long'&&r.crowdedLong||filter==='short'&&r.crowdedShort));
  }
  return {analyze,select,fresh,value,aligned,safeUrl};
});
