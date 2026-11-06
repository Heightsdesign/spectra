/* Physical references share only pixel geometry with the printed-frame editor. */
(function(root){
  'use strict';
  const G=root.SpectraReferenceGeometry, clone=v=>structuredClone(v);
  const keys=['status','endpoints','line_abc','uncertainty_pixels','notes','origin'];
  const snapshot=s=>Object.fromEntries(keys.map(k=>[k,clone(s[k])]));
  function edit(side,changes){
    Object.assign(side,changes);side.confirmed=false;side.confirmed_at_utc=null;side.reviewed=null;
  }
  function setPoints(side,points,origin='manual'){
    const line=G.fromPoints(...points);edit(side,{endpoints:clone(points),line_abc:line,origin});
  }
  function sideCheck(side,size){
    if(!['certain','uncertain','indeterminate'].includes(side.status))throw Error('Select a review status.');
    if(side.status==='indeterminate'){
      if(side.endpoints!==null||side.line_abc!==null||!side.notes.trim())throw Error('Indeterminate: explain uncertainty and clear geometry.');
      if(side.uncertainty_pixels!==null)throw Error('Indeterminate sides have no numeric uncertainty band.');
      return;
    }
    const p=side.endpoints;
    if(!Array.isArray(p)||p.length!==2||p.some(q=>!Array.isArray(q)||q.length!==2||q.some((v,i)=>!Number.isFinite(v)||v<0||v>=size[i])))throw Error('Two in-image original-pixel endpoints required.');
    if(Math.hypot(p[1][0]-p[0][0],p[1][1]-p[0][1])<1)throw Error('Endpoints must be at least one pixel apart.');
    const l=G.fromPoints(...p), n=Math.hypot(...side.line_abc.slice(0,2));
    if(!side.line_abc.every(Number.isFinite)||n<1e-10||p.some(q=>Math.abs(side.line_abc[0]*q[0]+side.line_abc[1]*q[1]+side.line_abc[2])/n>1e-6))throw Error('Line and endpoints disagree.');
    if(Math.abs(l[[0,2].includes(side.index)?1:0])<.1)throw Error('Incompatible side orientation.');
    if(side.status==='uncertain'){
      if(!Number.isFinite(side.uncertainty_pixels)||side.uncertainty_pixels<=0||!side.notes.trim())throw Error('Uncertain: provide a positive pixel band and explanation.');
    }else if(side.uncertainty_pixels!==null)throw Error('Only uncertain sides have an uncertainty band.');
  }
  function corners(sides,size){
    const points=sides.map((s,i)=>{
      const a=sides[(i+3)%4].line_abc,b=s.line_abc;if(!a||!b)return null;
      const det=a[0]*b[1]-b[0]*a[1];
      if(Math.abs(det)/(Math.hypot(...a.slice(0,2))*Math.hypot(...b.slice(0,2)))<.01)throw Error('Unstable adjacent-line intersections.');
      const p=[(a[1]*b[2]-b[1]*a[2])/det,(b[0]*a[2]-a[0]*b[2])/det];
      if(p.some((v,k)=>!Number.isFinite(v)||v<0||v>=size[k]))throw Error('Corner outside original image.');return p;
    });
    if(points.every(Boolean)){
      let area=0;const cross=[];
      for(let i=0;i<4;i++){const p=points[i],q=points[(i+1)%4],r=points[(i+2)%4];area+=p[0]*q[1]-q[0]*p[1];cross.push((q[0]-p[0])*(r[1]-q[1])-(q[1]-p[1])*(r[0]-q[0]));if(Math.hypot(q[0]-p[0],q[1]-p[1])<1)throw Error('Degenerate contour.');}
      if(area<=2||cross.some(v=>v<=0)||!(points[0][1]+points[1][1]<points[2][1]+points[3][1])||!(points[1][0]+points[2][0]>points[0][0]+points[3][0]))throw Error('Crossed, nonconvex or reordered contour.');
    }return points;
  }
  function confirm(side,size){sideCheck(side,size);side.confirmed=true;side.confirmed_at_utc=new Date().toISOString();side.reviewed=snapshot(side);}
  function validate(ref){
    if(!ref.reviewer.trim()||ref.independent_review_declared!==true)throw Error('Reviewer name and independent visual-review declaration required.');
    if(ref.sides.length!==4)throw Error('Four sides required.');
    for(let i=0;i<4;i++){
      const s=ref.sides[i];if(s.index!==i||s.name!==['top','right','bottom','left'][i])throw Error('Side ordering mismatch.');
      sideCheck(s,ref.image.dimensions);
      if(s.confirmed!==true||JSON.stringify(s.reviewed)!==JSON.stringify(snapshot(s)))throw Error('Each current side needs explicit confirmation.');
    }return corners(ref.sides,ref.image.dimensions);
  }
  const api={snapshot,edit,setPoints,sideCheck,corners,confirm,validate};root.SpectraPhysicalReference=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(globalThis);
