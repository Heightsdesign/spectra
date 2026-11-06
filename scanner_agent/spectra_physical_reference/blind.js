/* Dedicated manual-only offline pass. No comparison inputs or import controls. */
(function () {
  'use strict';
  const data=JSON.parse(document.getElementById('blind-data').textContent);
  const ref=data.reference, G=globalThis.SpectraReferenceGeometry, M=globalThis.SpectraPhysicalReference;
  const $=id=>document.getElementById(id), canvas=$('view'), ctx=canvas.getContext('2d');
  const image=new Image(), size=ref.image.dimensions;
  let selected=0, placing=false, points=[], drag=null, hover=null, locked=false;
  const camera={center:size.map(v=>v/2),zoom:1,width:canvas.width,height:canvas.height};
  const guard=fn=>(...args)=>{if(locked)return;try{fn(...args);}catch(e){$('message').textContent=e.message;}};
  function canvasBounds(){
    const r=canvas.getBoundingClientRect(), style=getComputedStyle(canvas);
    const left=parseFloat(style.borderLeftWidth)||0, right=parseFloat(style.borderRightWidth)||0;
    const top=parseFloat(style.borderTopWidth)||0, bottom=parseFloat(style.borderBottomWidth)||0;
    return {left:r.left+left,top:r.top+top,width:r.width-left-right,height:r.height-top-bottom};
  }
  function render(){
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.save();ctx.translate(canvas.width/2,canvas.height/2);ctx.scale(camera.zoom,camera.zoom);ctx.translate(-camera.center[0],-camera.center[1]);
    ctx.imageSmoothingEnabled=false;ctx.drawImage(image,0,0);ctx.restore();
    const bounds=canvasBounds(), sx=canvas.width/bounds.width, sy=canvas.height/bounds.height;
    ref.sides.forEach((s,i)=>{
      if(!s.endpoints)return;
      const [a,b]=s.endpoints.map(p=>G.imageToCanvas(p,camera));
      const active=(drag?.kind==='edit'&&drag.side===i)||hover?.side===i;
      ctx.strokeStyle=active?'#fff':i===selected?'#ffdf00':'#00d9ff';ctx.lineWidth=(active?3:i===selected?2:1)*sx;
      ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke();
      [a,b].forEach((p,k)=>{ctx.beginPath();ctx.ellipse(...p,7*sx,7*sy,0,0,Math.PI*2);ctx.fillStyle=(active&&(drag?.endpoint===k||hover?.endpoint===k))?'#ffdf00':'#18212b';ctx.fill();ctx.stroke();});
    });
    $('zoom').value=camera.zoom.toFixed(3);
    $('confirmations').textContent=ref.sides.map(s=>s.name+': '+(s.confirmed?'confirmed':'unconfirmed')).join(' | ');
  }
  function refresh(){
    const s=ref.sides[selected];$('status').value=s.status;$('notes').value=s.notes;$('uncertainty').value=s.uncertainty_pixels??'';
    ['x1','y1','x2','y2'].forEach((id,i)=>{$(id).value=s.endpoints?s.endpoints.flat()[i]:'';});render();
  }
  function fit(){camera.center=size.map(v=>v/2);camera.zoom=Math.min(canvas.width/size[0],canvas.height/size[1]);render();}
  function position(e){return G.clientToImage([e.clientX,e.clientY],canvasBounds(),camera);}
  function hit(e){
    const cursor=[e.clientX,e.clientY], bounds=canvasBounds(), handles=[], lines=[];
    ref.sides.forEach((side,i)=>{
      if(!side.endpoints)return;
      const p=side.endpoints.map(q=>G.imageToClient(q,bounds,camera));
      p.forEach((q,k)=>{const distance=Math.hypot(q[0]-cursor[0],q[1]-cursor[1]);if(distance<=11)handles.push({side:i,endpoint:k,distance});});
      const distance=G.segmentDistance(cursor,...p);if(distance<=7)lines.push({side:i,endpoint:null,distance});
    });
    // Endpoint handles always win over line bodies; active side breaks ties.
    const sort=(a,b)=>a.distance-b.distance||Number(b.side===selected)-Number(a.side===selected);
    return handles.sort(sort)[0]??lines.sort(sort)[0]??null;
  }
  function feedback(){
    canvas.style.cursor=locked?'default':drag?(drag.kind==='pan'?'grabbing':drag.endpoint===null?'grabbing':'crosshair'):placing?'crosshair':hover?(hover.endpoint===null?'grab':'crosshair'):'grab';
    canvas.dataset.interaction=drag?drag.kind==='pan'?'panning':drag.endpoint===null?'dragging-line':'dragging-endpoint':hover?hover.endpoint===null?'line':'endpoint':'pan';
  }
  $('identity').textContent='Session '+data.session_id+' | original SHA-256 '+ref.image.sha256+' | '+size.join(' × ');
  $('side').onchange=guard(()=>{selected=$('side').selectedIndex;placing=false;points=[];refresh();});
  $('place').onclick=guard(()=>{placing=true;points=[];hover=null;feedback();render();$('message').textContent='Click two points for '+ref.sides[selected].name+'.';});
  $('clear').onclick=guard(()=>{M.edit(ref.sides[selected],{endpoints:null,line_abc:null});refresh();});
  $('fit').onclick=guard(fit);
  $('zoom').onchange=guard(()=>{const value=Number($('zoom').value);if(!Number.isFinite(value)||value<.1||value>64)throw Error('Zoom must be 0.1–64.');camera.zoom=value;render();});
  $('apply').onclick=guard(()=>{const inputs=['x1','y1','x2','y2'].map(id=>$(id).value);if(inputs.some(v=>!v.trim()))throw Error('Enter all four coordinates.');const p=inputs.map(Number);M.setPoints(ref.sides[selected],[p.slice(0,2),p.slice(2)]);refresh();});
  function statusEdit(){const status=$('status').value;M.edit(ref.sides[selected],{status,notes:$('notes').value,uncertainty_pixels:status==='uncertain'&&$('uncertainty').value!==''?Number($('uncertainty').value):null,...(status==='indeterminate'?{endpoints:null,line_abc:null}:{})});refresh();}
  for(const id of ['status','notes','uncertainty'])$(id).onchange=guard(statusEdit);
  $('confirm').onclick=guard(()=>{statusEdit();M.confirm(ref.sides[selected],size);refresh();});
  canvas.onpointerdown=guard(e=>{
    if(e.button!==0&&e.button!==1)return;
    e.preventDefault();
    const p=position(e);
    if(placing&&e.button===0&&!e.shiftKey){if(p.some((v,i)=>v<0||v>=size[i]))throw Error('Place points inside original image.');points.push(p);if(points.length===2){M.setPoints(ref.sides[selected],points);placing=false;points=[];feedback();refresh();}return;}
    const target=!e.shiftKey&&e.button===0?hit(e):null;
    if(target){
      selected=target.side;$('side').selectedIndex=selected;
      drag={kind:'edit',side:selected,endpoint:target.endpoint,start:p,points:structuredClone(ref.sides[selected].endpoints),pointerId:e.pointerId};
      $('message').textContent=target.endpoint===null?'Dragging whole line; orientation and length preserved.':'Dragging endpoint '+(target.endpoint+1)+'.';
    }else{
      drag={kind:'pan',start:[e.clientX,e.clientY],center:[...camera.center],pointerId:e.pointerId};
    }
    hover=target;canvas.setPointerCapture(e.pointerId);feedback();refresh();
  });
  canvas.onpointermove=guard(e=>{
    if(!drag){hover=placing?null:hit(e);feedback();render();return;}
    if(e.pointerId!==drag.pointerId)return;
    if(drag.kind==='pan'){
      const bounds=canvasBounds();
      camera.center=drag.center.map((v,i)=>v-([e.clientX,e.clientY][i]-drag.start[i])*[canvas.width/bounds.width,canvas.height/bounds.height][i]/camera.zoom);
      render();return;
    }
    const next=G.move(drag.points,drag.start,position(e),drag.endpoint);
    if(next.some(p=>p.some((v,i)=>v<0||v>=size[i]))||Math.hypot(next[1][0]-next[0][0],next[1][1]-next[0][1])<1){$('message').textContent='Keep both endpoints inside the original image and at least one pixel apart.';return;}
    if(JSON.stringify(next)!==JSON.stringify(ref.sides[drag.side].endpoints)){M.setPoints(ref.sides[drag.side],next);refresh();}
  });
  function finish(e){if(drag&&e.pointerId!==drag.pointerId)return;drag=null;hover=locked||placing?null:hit(e);if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);feedback();render();}
  canvas.onpointerup=finish;canvas.onpointercancel=finish;
  canvas.onlostpointercapture=()=>{drag=null;feedback();render();};
  canvas.onpointerleave=()=>{if(!drag){hover=null;feedback();render();}};
  canvas.onwheel=guard(e=>{e.preventDefault();if(drag)return;const before=position(e);camera.zoom=Math.max(.1,Math.min(64,camera.zoom*Math.exp(-e.deltaY*.001)));const after=position(e);camera.center=camera.center.map((v,i)=>v+before[i]-after[i]);hover=null;feedback();render();});
  $('export').onclick=guard(async()=>{
    try{
      ref.reviewer=$('reviewer').value.trim();ref.independent_review_declared=$('declaration').checked;
      if(!['none','exposed','unknown'].includes($('exposure').value))throw Error('Declare prior exposure explicitly.');
      M.validate(ref);
      const raw=JSON.stringify(ref,null,2)+'\n';
      const exposure=$('exposure').value;
      locked=true;document.querySelectorAll('input,select,textarea,button').forEach(e=>{e.disabled=true;});
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw))),b=>b.toString(16).padStart(2,'0')).join('');
      const bundle={schema_version:1,kind:'blind_first_pass_export',session_id:data.session_id,exported_at_utc:new Date().toISOString(),blind_review_declared:true,prior_detector_exposure:exposure,reference_sha256:hash,reference_json:raw};
      const url=URL.createObjectURL(new Blob([JSON.stringify(bundle,null,2)],{type:'application/json'}));
      const link=document.createElement('a');link.href=url;link.download='blind-first-pass-'+data.session_id+'.json';link.click();
      locked=true;document.querySelectorAll('input,select,textarea,button').forEach(e=>{e.disabled=true;});
      $('message').textContent='First pass exported and page locked. SHA-256 '+hash+'. Coordinator must freeze this export before comparison. Local files and declarations are not tamper-proof.';
      setTimeout(()=>URL.revokeObjectURL(url),10000);
    }catch(e){locked=false;document.querySelectorAll('input,select,textarea,button').forEach(el=>{el.disabled=false;});$('message').textContent=e.message;}
  });
  image.onload=()=>{fit();refresh();};image.src=data.image;
})();
