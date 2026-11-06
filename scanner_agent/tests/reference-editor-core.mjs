import assert from 'node:assert/strict';
import G from '../spectra_reference/editor-core.js';

const close = (a,b,tolerance=1e-10) => assert.ok(Math.abs(a-b)<=tolerance, `${a} != ${b}`);
const pointClose = (a,b) => a.forEach((v,i)=>close(v,b[i]));
const bounds = { left:53.25, top:111.75, width:713.5, height:421.25 };
const corners = [[0,0],[400,0],[400,600],[0,600]];
let count=0;
for (const zoom of [.25,.5,1,2,8,16]) {
  const camera={center:[177.123456789,233.987654321],zoom,width:1100,height:650};
  const original=[191.62465593,280.938462197];
  pointClose(G.clientToImage(G.imageToClient(original,bounds,camera),bounds,camera),original);
  const moved=[original[0]+2.125,original[1]-.375];
  const points=[[30.123456789,40.987654321],[330.5,41.5]];
  const proposal=G.move(points,G.clientToImage(G.imageToClient(original,bounds,camera),bounds,camera),
    G.clientToImage(G.imageToClient(moved,bounds,camera),bounds,camera));
  pointClose(proposal[0],[points[0][0]+2.125,points[0][1]-.375]);
  pointClose(proposal[1],[points[1][0]+2.125,points[1][1]-.375]);
  const endpoint=G.move(points,original,moved,0);
  pointClose(endpoint[0],proposal[0]);assert.deepEqual(endpoint[1],points[1]);
  const anchor=[201.2,102.7], anchored=G.canvasToImage(anchor,camera);
  pointClose(G.canvasToImage(anchor,G.zoomAt(camera,anchor,zoom*1.3)),anchored);
  count++;
}
const points=[[20,30],[200,31]];
pointClose(G.move(points,[0,0],[10,20],null,.1)[0],[21,32]);
const reference=G.fromOffsets(corners,0,[.18,.82],[20,24]);
close(G.atLine(corners,0,reference.line,.18).distance,20);
close(G.atLine(corners,0,reference.line,.82).distance,24);
const line=G.fromPoints(...reference.points);
const afterImport=JSON.parse(JSON.stringify(line));
assert.deepEqual(afterImport,line);
// Hundreds of previews from one snapshot must not accumulate floating-point deltas.
let preview;
for(let i=0;i<1000;i++)preview=G.move(points,[.123,.456],[.123+i*.001,.456+i*.003],1);
assert.deepEqual(preview,G.move(points,[.123,.456],[1.122,3.453],1));
const history=new G.History(200);
const before={sides:[{line_abc:[0,1,-20],status:'annotated'}]};
const after={sides:[{line_abc:[0,1,-21.123456789],status:'unannotated'}]};
history.push(before,after,0);
assert.deepEqual(history.undo().state,before);
assert.deepEqual(history.redo().state,after);
assert.equal(history.push(after,after,0),false);
history.undo();history.push(before,{sides:[]},1);assert.equal(history.redo(),null);
assert.throws(()=>G.fromPoints([1,1],[1,1]));
assert.throws(()=>G.atLine(corners,0,[1,0,-20],.5));
console.log(`Editor core: passed (${count} zoom/scaled-viewport cases; translation, endpoints, anchored zoom, fine movement, offsets, exact history, no preview drift).`);
