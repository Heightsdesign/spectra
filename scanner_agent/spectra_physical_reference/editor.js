'use strict';
const data=JSON.parse(document.getElementById('payload').textContent);
const reference=structuredClone(data.reference), G=SpectraReferenceGeometry, P=SpectraPhysicalReference;
const $=id=>document.getElementById(id), canvas=$('view'), ctx=canvas.getContext('2d');
const image=new Image(), size=reference.image.dimensions, history=new G.History();
const numericDrafts=[null,null,null,null], detailViews=[];
let active=0, placing=null, drag=null, preview=null, lastExport=null;
let camera={center:size.map(v=>v/2),zoom:1,width:canvas.width,height:canvas.height};
const fallback=[[size[0]*.2,size[1]*.2],[size[0]*.8,size[1]*.2],[size[0]*.8,size[1]*.8],[size[0]*.2,size[1]*.8]];
const anchors=data.reports.find(r=>r.baseline?.geometry)?.baseline.geometry.corners_pixels??fallback;
// Color is redundant with report-local IDs, version prefixes and dash patterns.
const layerPalette=['#0072B2','#E69F00','#009E73','#CC79A7','#D55E00','#56B4E9','#F0E442','#882255','#332288'];
const selectedCandidates=[null,null,null,null];
const candidates=data.reports.flatMap((r,j)=>(r.baseline.sides??[]).flatMap(s=>(s.candidate_layers??[{id:'selected',line_abc:s.line_abc}]).map((l,k)=>({
  side:s.index,line:l.line_abc,layerId:l.id,version:r.algorithm_version,phase:r.experimental_phase??'',
  family:r.algorithm_version==='0.2.0'?'frozen':'experimental',reportIndex:j,
  label:`${r.algorithm_version} ${r.experimental_phase??''} / ${l.id}`,
  shortLabel:`${r.algorithm_version==='0.2.0'?'F':'E'}${j+1}:${l.id}`,
  key:`${j}-${s.index}-${l.id}`,color:layerPalette[k%layerPalette.length],
  coverage:l.coverage,score:l.support_score,failures:l.criterion_failures,
  ambiguity:s.ambiguity_reasons,admissible:l.physical_criterion_passed,
  provisional:l.selected===true||s.selected_layer_id===l.id,disposition:l.disposition
}))));
function candidateVisible(c){return $('candidates').checked&&$(c.family==='frozen'?'showFrozen':'showExperimental').checked;}
function candidatePaintPlan(side){
  const selected=candidates.some(c=>c.key===selectedCandidates[side]&&candidateVisible(c))?selectedCandidates[side]:null;
  return candidates.filter(c=>c.side===side&&candidateVisible(c)).map(c=>({...c,
    highlighted:c.key===selected,alpha:(selected&&c.key!==selected)?0.18:1,
    width:c.key===selected?2.5:1,dash:c.family==='frozen'?[9,5]:[2,4]
  })).sort((a,b)=>Number(a.highlighted)-Number(b.highlighted));
}
function selectCandidate(key){selectedCandidates[active]=key||null;$('candidate').value=key||'';updateCandidatePanel();draw();}
function updateCandidatePanel(){
  const c=candidates.find(c=>c.key===selectedCandidates[active]);
  const info=c?[
    `Detector ${c.version}${c.phase?' / '+c.phase:''} | layer ${c.layerId} | label ${c.shortLabel}`,
    `Coverage: ${Number.isFinite(c.coverage)?(100*c.coverage).toFixed(1)+'%':'unavailable'} | support score (not probability): ${Number.isFinite(c.score)?String(c.score):'unavailable'}`,
    `Criterion failures: ${Array.isArray(c.failures)?c.failures.join(', ')||'none':'unavailable'}`,
    `Physical admissibility: ${typeof c.admissible==='boolean'?(c.admissible?'passed':'failed'):'unavailable'}`,
    `Ambiguity on this side: ${Array.isArray(c.ambiguity)?c.ambiguity.join(', ')||'none':'unavailable'}`,
    `Detector provisional selection: ${c.provisional?'yes':'no'} | disposition: ${c.disposition??'unavailable'}`,
    `Overlay: ${candidateVisible(c)?'visible (if within view)':'hidden; enable Show candidates and its detector version'}`,
    'Automatic candidate only. Selecting it does not place, change or confirm a human reference.'
  ].join('\n'):'Choose a candidate to inspect its metadata. Layer IDs are local to each detector report; matching IDs do not establish correspondence.';
  if($('candidateInfo').textContent!==info)$('candidateInfo').textContent=info;
  $('showSelected').disabled=!c;
  const legend=$('candidateLegend');legend.replaceChildren();
  for(const item of candidates.filter(c=>c.side===active)){
    const button=document.createElement('button');button.type='button';button.className='candidate-entry';
    button.dataset.candidateKey=item.key;button.setAttribute('aria-pressed',String(item.key===selectedCandidates[active]));
    const swatch=document.createElement('span');swatch.className='candidate-swatch';swatch.style.borderColor=item.color;swatch.style.borderTopStyle=item.family==='frozen'?'dashed':'dotted';swatch.setAttribute('aria-hidden','true');
    button.append(swatch,document.createTextNode(`${item.shortLabel} ? ${item.label}${item.provisional?' (provisional selection)':''}${candidateVisible(item)?'':' (hidden)'}`));
    button.onclick=()=>selectCandidate(item.key);legend.append(button);
  }
}
function labelAnchor(line,cam,width){
  const normal=line.slice(0,2), origin=G.imageToCanvas([0,0],cam);
  const c=line[2]*cam.zoom-normal[0]*origin[0]-normal[1]*origin[1],hits=[];
  for(const x of [2,width-4])if(Math.abs(normal[1])>1e-8){const y=-(normal[0]*x+c)/normal[1];if(y>=2&&y<=cam.height-2)hits.push([x,y]);}
  for(const y of [2,cam.height-2])if(Math.abs(normal[0])>1e-8){const x=-(normal[1]*y+c)/normal[0];if(x>=2&&x<=width-4)hits.push([x,y]);}
  return hits.sort((a,b)=>b[0]-a[0]||Math.abs(a[1]-cam.height/2)-Math.abs(b[1]-cam.height/2))[0];
}
function drawCandidateLabels(context,cam,plan,viewport){
  const rows=plan.map(c=>({...c,anchor:labelAnchor(c.line,cam,viewport)})).filter(c=>c.anchor);
  rows.sort((a,b)=>a.anchor[1]-b.anchor[1]||a.key.localeCompare(b.key));
  context.save();context.fillStyle='#171717';context.fillRect(viewport,0,cam.width-viewport,cam.height);
  context.fillStyle='white';context.font='11px system-ui';context.fillText('AUTO candidates',viewport+7,15);
  const spacing=Math.min(18,(cam.height-78)/Math.max(1,rows.length));
  const start=Math.max(32,Math.min((rows[0]?.anchor[1]??32),cam.height-60-rows.length*spacing));
  rows.forEach((c,i)=>{
    const y=start+i*spacing;
    context.globalAlpha=c.highlighted?1:Math.max(.5,c.alpha);context.strokeStyle=c.color;context.lineWidth=c.highlighted?2:1;context.setLineDash(c.dash);
    context.beginPath();context.moveTo(...c.anchor);context.lineTo(viewport+5,y-3);context.stroke();context.setLineDash([]);
    context.fillStyle=c.color;context.fillRect(viewport+7,y-9,5,10);context.fillStyle='white';context.font=`${c.highlighted?'bold ':''}11px system-ui`;
    context.fillText(`${c.highlighted?'> ':''}${c.shortLabel}${c.provisional?' *':''}`,viewport+17,y);
  });
  context.globalAlpha=1;context.font='10px system-ui';context.fillStyle='#ddd';context.fillText('* detector-selected',viewport+5,cam.height-35);
  context.fillStyle='white';context.fillText('REF = reference/draft',viewport+5,cam.height-19);context.fillText('confirm explicitly',viewport+5,cam.height-5);context.restore();
}
function error(e){$('error').textContent=e?.message??String(e??'');}
function attempt(fn){try{error('');fn();}catch(e){error(e);}}
function current(){return reference.sides[active];}
function mutate(fn){const before=structuredClone(reference.sides);fn();history.push(before,reference.sides,active);render();}
function ensureApplied(){if(numericDrafts.some(Boolean))throw Error('Apply or clear pending endpoint drafts before confirming or exporting.');}
function linePoints(l,i){return [.18,.82].map(t=>G.atLine(anchors,i,l,t).point);}
function focus(){const s=current(), p=s.endpoints??[anchors[active],anchors[(active+1)%4]];camera.center=p[0].map((v,k)=>(v+p[1][k])/2);render();}
function drawLine(context,l,color,cameraFor,dashed=false,width=1,alpha=1,dash=null){
  const norm=Math.hypot(l[0],l[1]), origin=[-l[0]*l[2]/norm**2,-l[1]*l[2]/norm**2], tangent=[-l[1]/norm,l[0]/norm];
  const a=G.imageToCanvas(origin.map((v,k)=>v-20000*tangent[k]),cameraFor), b=G.imageToCanvas(origin.map((v,k)=>v+20000*tangent[k]),cameraFor);
  context.save();context.globalAlpha=alpha;context.strokeStyle=color;context.lineWidth=width;context.setLineDash(dash??(dashed?[6,5]:[]));context.beginPath();context.moveTo(...a);context.lineTo(...b);context.stroke();context.restore();
}
function drawScene(context,cam,lines=true,side=active){
  const viewport=cam.width-(cam.width>500?180:110),plan=candidatePaintPlan(side);
  context.clearRect(0,0,cam.width,cam.height);context.fillStyle='#111';context.fillRect(0,0,cam.width,cam.height);context.imageSmoothingEnabled=false;
  context.save();context.beginPath();context.rect(0,0,viewport,cam.height);context.clip();
  const p=G.imageToCanvas([0,0],cam);context.drawImage(image,p[0],p[1],size[0]*cam.zoom,size[1]*cam.zoom);
  for(const c of plan){
    drawLine(context,c.line,'#111',cam,true,c.width+2,c.alpha,c.dash);
    drawLine(context,c.line,c.color,cam,true,c.width,c.alpha,c.dash);
  }
  if(lines)for(const s of reference.sides){
    const l=s.index===active&&preview?G.fromPoints(...preview):s.line_abc;
    if(l){drawLine(context,l,'black',cam,!s.confirmed,6);drawLine(context,l,s.status==='uncertain'?'#ffa64a':s.confirmed?'#36ec8b':'#ffe15d',cam,!s.confirmed,3);}
  }
  context.restore();drawCandidateLabels(context,cam,plan,viewport);
  if(lines&&reference.sides.some(s=>s.line_abc)){
    context.save();context.font='bold 12px system-ui';context.fillStyle='#111';context.fillRect(0,0,viewport,20);context.fillStyle='white';context.fillText('REF: thick outlined reference / draft lines ? confirmation remains explicit',6,14);context.restore();
  }
}
function draw(){
  if(!image.complete||!image.naturalWidth)return;
  drawScene(ctx,camera);
  const p=preview??current().endpoints;
  if(p)for(const q of p){const at=G.imageToCanvas(q,camera);ctx.fillStyle='#ff9a35';ctx.fillRect(at[0]-4,at[1]-4,8,8);}
  const z=Number($('detailZoom').value), t=Number($('along').value);
  let corners;try{corners=P.corners(reference.sides,size);}catch{corners=anchors;}
  for(let i=0;i<8;i++){
    const view=detailViews[i], side=reference.sides[i%4];let center;
    if(i<4){const ends=side.endpoints??[anchors[i],anchors[(i+1)%4]];center=ends[0].map((v,k)=>v+t*(ends[1][k]-v));}
    else center=corners[i-4]??anchors[i-4];
    view.camera={center,zoom:z,width:view.canvas.width,height:view.canvas.height};drawScene(view.canvas.getContext('2d'),view.camera,$('detailLines').checked,i%4);
  }
}
function render(){
  const s=current();$('status').value=s.status;$('notes').value=s.notes;$('uncertainty').value=s.uncertainty_pixels??'';
  const vals=numericDrafts[active]??s.endpoints?.flat()??['','','',''];['x0','y0','x1','y1'].forEach((id,i)=>{$(id).value=vals[i];});
  $('candidate').replaceChildren(new Option('None',''));for(const c of candidates.filter(c=>c.side===active))$('candidate').add(new Option(`${c.shortLabel} ? ${c.label}`,c.key));$('candidate').value=selectedCandidates[active]??'';updateCandidatePanel();
  $('progress').textContent=reference.sides.map(s=>`${s.name}: ${s.confirmed?'confirmed '+s.status:'unconfirmed'}`).join(' | ');
  $('zoom').value=camera.zoom;$('state').textContent=JSON.stringify(reference.sides,null,2);draw();
}
function commitPoints(points,origin='manual'){mutate(()=>P.setPoints(current(),points,origin));}
function translate(dx,dy){ensureApplied();if(!current().endpoints)throw Error('Place a line first.');commitPoints(current().endpoints.map(p=>[p[0]+dx,p[1]+dy]));}
function nudge(sign){const s=current();if(!s.line_abc)throw Error('Place a line first.');let n=s.line_abc.slice(0,2), inside=[[0,1],[-1,0],[0,-1],[1,0]][active];if(n[0]*inside[0]+n[1]*inside[1]<0)n=n.map(v=>-v);const step=Number($('step').value);if(!Number.isFinite(step)||step<=0)throw Error('Positive pixel step required.');translate(sign*step*n[0],sign*step*n[1]);}
$('side').onchange=()=>{active=$('side').selectedIndex;placing=null;preview=null;render();};
$('zoom').onchange=()=>attempt(()=>{const z=Number($('zoom').value);if(!Number.isFinite(z)||z<.25||z>16)throw Error('Zoom range: 0.25ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œ16.');camera.zoom=z;draw();});
$('fit').onclick=()=>{camera.center=size.map(v=>v/2);camera.zoom=Math.max(.25,Math.min(16,Math.min(1100/size[0],650/size[1])));render();};
$('focus').onclick=focus;
for(const id of ['candidates','showFrozen','showExperimental'])$(id).onchange=()=>{if(candidates.some(candidateVisible))reference.candidate_overlays_seen=true;updateCandidatePanel();draw();};
$('candidate').onchange=()=>selectCandidate($('candidate').value);
$('showSelected').onclick=()=>{const c=candidates.find(c=>c.key===selectedCandidates[active]);if(!c)return;$('candidates').checked=true;$(c.family==='frozen'?'showFrozen':'showExperimental').checked=true;reference.candidate_overlays_seen=true;updateCandidatePanel();draw();};
for(const id of ['detailZoom','along','detailLines'])$(id).oninput=draw;
$('place').onclick=()=>{placing=[];error('Click two original-image points for the active physical side.');};
$('clear').onclick=()=>mutate(()=>{P.edit(current(),{endpoints:null,line_abc:null});numericDrafts[active]=null;});
$('seed').onclick=()=>attempt(()=>{ensureApplied();const c=candidates.find(c=>c.key===$('candidate').value);if(!c)throw Error('Choose a candidate first.');reference.candidate_overlays_seen=true;commitPoints(linePoints(c.line,active),'detector_seed');});
for(const id of ['status','notes','uncertainty'])$(id).onchange=()=>attempt(()=>{
  const status=$('status').value,notes=$('notes').value,raw=$('uncertainty').value;
  mutate(()=>{const changes={status,notes,uncertainty_pixels:status==='uncertain'&&raw!==''?Number(raw):null};if(status==='indeterminate'){changes.endpoints=null;changes.line_abc=null;numericDrafts[active]=null;}P.edit(current(),changes);});
});
for(const id of ['x0','y0','x1','y1'])$(id).oninput=()=>{numericDrafts[active]=['x0','y0','x1','y1'].map(id=>$(id).value);P.edit(current(),{});$('progress').textContent='Endpoint draft pending; confirmations invalidated. Apply endpoints before export.';};
$('apply').onclick=()=>attempt(()=>{const values=['x0','y0','x1','y1'].map(id=>$(id).value);if(values.some(v=>!v.trim()))throw Error('All endpoint coordinates required.');const n=values.map(Number);if(n.some(v=>!Number.isFinite(v)))throw Error('Finite endpoints required.');G.fromPoints([n[0],n[1]],[n[2],n[3]]);numericDrafts[active]=null;commitPoints([[n[0],n[1]],[n[2],n[3]]]);});
$('inward').onclick=()=>attempt(()=>nudge(1));$('outward').onclick=()=>attempt(()=>nudge(-1));
$('confirm').onclick=()=>attempt(()=>{ensureApplied();mutate(()=>P.confirm(current(),size));});
for(const [id,method] of [['undo','undo'],['redo','redo']])$(id).onclick=()=>{const previous=history[method]();if(previous){reference.sides=previous.state;active=previous.side;$('side').selectedIndex=active;numericDrafts.fill(null);/* Restored geometry must be re-reviewed. */reference.sides.forEach(s=>P.edit(s,{}));render();}};
$('reviewer').oninput=()=>{reference.reviewer=$('reviewer').value;};$('independent').onchange=()=>{reference.independent_review_declared=$('independent').checked;};
function buildExport(){ensureApplied();P.validate(reference);const value=structuredClone(reference);value.annotation_version=crypto.randomUUID();value.created_at_utc=new Date().toISOString();return value;}
$('download').onclick=()=>attempt(()=>{lastExport=buildExport();const url=URL.createObjectURL(new Blob([JSON.stringify(lastExport,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`physical-boundary-${lastExport.annotation_id}-${lastExport.annotation_version}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);});
canvas.onpointerdown=e=>attempt(()=>{
  ensureApplied();const point=G.clientToImage([e.clientX,e.clientY],canvas.getBoundingClientRect(),camera);canvas.focus();
  if(placing){placing.push(point);if(placing.length===2){commitPoints(placing);placing=null;error('Line placed, still unconfirmed.');}return;}
  const p=current().endpoints;let endpoint=null,kind='pan';
  if(p&&!$('pan').checked){endpoint=p.findIndex(q=>Math.hypot(q[0]-point[0],q[1]-point[1])*camera.zoom<12);if(endpoint<0)endpoint=null;if(endpoint!==null||G.segmentDistance(point,...p)*camera.zoom<8)kind='edit';}
  drag={point,center:[...camera.center],points:structuredClone(p),endpoint,kind,factor:($('fine').checked||e.shiftKey)?0.1:1,camera:structuredClone(camera)};canvas.setPointerCapture(e.pointerId);
});
canvas.onpointermove=e=>{if(!drag)return;const point=G.clientToImage([e.clientX,e.clientY],canvas.getBoundingClientRect(),drag.camera);if(drag.kind==='pan'){camera.center=drag.center.map((v,k)=>v-(point[k]-drag.point[k]));}else preview=G.move(drag.points,drag.point,point,drag.endpoint,drag.factor);draw();};
canvas.onpointerup=e=>attempt(()=>{if(!drag)return;const next=preview;drag=null;preview=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);if(next)commitPoints(next);else render();});
canvas.onpointercancel=()=>{drag=null;preview=null;draw();};
canvas.onwheel=e=>{e.preventDefault();const b=canvas.getBoundingClientRect(),p=[(e.clientX-b.left)*1100/b.width,(e.clientY-b.top)*650/b.height];camera=G.zoomAt(camera,p,camera.zoom*Math.exp(-e.deltaY*.002));render();};
canvas.onkeydown=e=>{if(!e.key.startsWith('Arrow'))return;e.preventDefault();attempt(()=>{const step=e.shiftKey?0.1:1;translate((e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0)*step,(e.key==='ArrowDown'?1:e.key==='ArrowUp'?-1:0)*step);});};
for(let i=0;i<8;i++){const box=document.createElement('div'),label=document.createElement('p'),c=document.createElement('canvas');label.textContent=i<4?`${reference.sides[i].name} edge`:`corner ${i-4} (line intersections are extrapolated)`;c.width=460;c.height=Math.max(360,80+16*Math.max(1,...reference.sides.map(s=>candidates.filter(c=>c.side===s.index).length)));c.setAttribute('aria-label',label.textContent);box.append(label,c);$('details').append(box);const view={canvas:c,camera:null};detailViews.push(view);c.onclick=e=>{if(!view.camera)return;camera.center=G.clientToImage([e.clientX,e.clientY],c.getBoundingClientRect(),view.camera);camera.zoom=Number($('detailZoom').value);camera.zoom=Math.min(16,camera.zoom);render();};}
$('identity').textContent=JSON.stringify({image:reference.image,source_reports:reference.source_reports,annotation_id:reference.annotation_id},null,2);
image.onload=()=>{if(image.naturalWidth!==size[0]||image.naturalHeight!==size[1]){error('Embedded image identity/dimensions mismatch.');return;}$('fit').click();render();};image.src=data.image;
