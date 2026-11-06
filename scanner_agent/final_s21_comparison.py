"""Read-only acquisition comparison; all generated artifacts in a new directory."""
import sys, json, hashlib, struct, math
from pathlib import Path
from functools import partial
import cv2
import numpy as np
from PIL import Image
from spectra_boundary.analysis import analyze
from spectra_boundary.config import configuration
from spectra_boundary.controlled_detector import detect
from spectra_boundary.controlled_layers import select_layers

ROOT = Path(__file__).resolve().parent
EXP = ROOT / 'local_data/photometric-exp2/20261019T011050Z'
sys.path.insert(0, str(EXP))
from photometric_exp2 import enrich, extract_candidate, gray_image
OUT = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT / 'local_data/final-s21-acquisition-comparison-20261019-v2'
IDS = ['20261019T113228_581d4ca7d5424bf99075f64a409ecbfd','20261019T113443_29e582152efc47d8801d7f5ef6d755cd','20261019T113537_456a2a9b8a1b4184b31e0fdbf58aaa33']
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
    with p.open('x',encoding='utf-8') as f: json.dump(v,f,indent=2,allow_nan=False)
def transform(p,H): return cv2.perspectiveTransform(np.float64(p).reshape(-1,1,2),H).reshape(-1,2)
def main():
    OUT.mkdir(exist_ok=False)
    protected = {}
    for d in [ROOT/'spectra_boundary', ROOT/'spectra_pipeline', ROOT/'spectra_physical_reference', EXP]:
        for p in d.rglob('*'):
            if p.is_file() and p.suffix in ('.py','.json','.md') and '__pycache__' not in p.parts: protected[str(p)]=sha(p)
    for rid in IDS:
        for p in (ROOT/'local_data/rd_pipeline/runs'/rid).rglob('*'):
            if p.is_file(): protected[str(p)]=sha(p)
    write(OUT/'protected-before.json',protected)
    cfg=configuration({}); images=[]; records=[]; reports=[]; phases=[]
    for i,rid in enumerate(IDS):
        run=ROOT/'local_data/rd_pipeline/runs'/rid
        p=next(run.rglob('original.bmp')); meta=json.loads(p.with_name('metadata.json').read_text())
        folder=OUT/f'capture-{i+1}'; folder.mkdir()
        b=p.read_bytes(); off=struct.unpack_from('<I',b,10)[0]; w,h=struct.unpack_from('<ii',b,18); bits=struct.unpack_from('<H',b,28)[0]; comp=struct.unpack_from('<I',b,30)[0]
        with Image.open(p) as im:
            im.load(); rgb=np.asarray(im).copy(); info=im.info; mode=im.mode
        expected=off+((w*bits+31)//32)*4*abs(h)
        assert len(b)>=expected and len(b)==struct.unpack_from('<I',b,2)[0] and bits==24 and comp==0
        assert sha(p)==meta['sha256'] and meta['complete'] and rgb.shape==(abs(h),w,3)
        images.append(rgb)
        rec=dict(run=rid,original=str(p),sha256=sha(p),pixel_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),bytes=len(b),dimensions=[w,abs(h)],mode=mode,bits_per_pixel=bits,compression=comp,pixel_offset=off,expected_complete_size=expected,readable_all_pixels=True,pixel_min=rgb.min(axis=(0,1)).tolist(),pixel_max=rgb.max(axis=(0,1)).tolist(),pixel_std=rgb.std(axis=(0,1)).tolist(),embedded=info,metadata_complete=meta['complete'],metadata=meta)
        rec['trailing_bytes_after_pixel_array']=len(b)-expected
        rec['declared_pixel_array_bytes']=struct.unpack_from('<I',b,34)[0]
        records.append(rec)
        frozen=analyze(p,folder/'frozen',cfg); reports.append(frozen)
        phase,_,_,_=detect(rgb,info.get('dpi'),cfg,layer_selector=partial(select_layers,support_reassignment=True)); phases.append(phase)
        phase_report=dict(frozen,algorithm_version='0.3.0-exp1',baseline=phase,status=phase['status'])
        write(folder/'phase2.json',phase_report)
        exp=enrich(rgb,phase_report); write(folder/'exp2.json',exp)
        candidates=[]
        for mode_name,det in [('frozen',frozen['baseline']),('phase2',phase)]:
            for side in det.get('sides',[]):
                for layer in side['candidate_layers']:
                    features,raw=extract_candidate(gray_image(rgb),side,layer,cfg)
                    name=f"{mode_name}-side-{side['index']}-{layer['id']}"
                    write(folder/(name+'-features.json'),features); np.savez_compressed(folder/(name+'-profiles.npz'),**raw)
                    candidates.append(dict(mode=mode_name,side=side['index'],layer=layer,features=features))
        write(folder/'candidates.json',candidates)
        thumb=cv2.resize(rgb,(501,645)); Image.fromarray(thumb).save(folder/'original-preview.png')
        print('analyzed',i+1,frozen['status'],flush=True)
    write(OUT/'acquisitions.json',records)
    # SIFT interior print landmarks; no detected physical edge participates in the fit.
    grays=[cv2.cvtColor(a,cv2.COLOR_RGB2GRAY) for a in images]
    sift=cv2.SIFT_create(nfeatures=12000)
    features=[]
    corners=np.array(reports[0]['baseline']['geometry']['corners_pixels'])
    center=corners.mean(axis=0)
    for g in grays:
        # Conservative interior mask from each provisional quadrilateral, inset 100 px.
        idx=len(features); c=np.array(reports[idx]['baseline']['geometry']['corners_pixels']); cc=c.mean(axis=0)
        c=cc+(c-cc)*.78; mask=np.zeros(g.shape,np.uint8); cv2.fillConvexPoly(mask,np.int32(c),255)
        features.append(sift.detectAndCompute(g,mask))
    Hs=[np.eye(3)]; registrations=[dict(capture=1,angle_degrees=0,reference=True)]
    rng=np.random.default_rng(2102)
    for i in [1,2]:
        k0,d0=features[0]; ki,di=features[i]
        matches=cv2.BFMatcher().knnMatch(di,d0,k=2); good=[a for a,b in matches if a.distance<.70*b.distance]
        src=np.float64([ki[m.queryIdx].pt for m in good]); dst=np.float64([k0[m.trainIdx].pt for m in good])
        A,inliers=cv2.estimateAffinePartial2D(src,dst,method=cv2.RANSAC,ransacReprojThreshold=2,maxIters=10000,confidence=.999)
        keep=inliers.ravel().astype(bool); src=src[keep]; dst=dst[keep]
        # Deterministic spatially interleaved holdout, refit and evaluate without held points.
        order=np.lexsort((src[:,1],src[:,0])); test=order[::5]; train=np.setdiff1d(np.arange(len(src)),test)
        At,_=cv2.estimateAffinePartial2D(src[train],dst[train],method=cv2.LMEDS)
        H=np.vstack([A,[0,0,1]]); Hs.append(H)
        residual=np.linalg.norm(transform(src,H)-dst,axis=1)
        hold=np.linalg.norm(transform(src[test],np.vstack([At,[0,0,1]]))-dst[test],axis=1)
        query=np.vstack([corners,center]); boot=[]
        for _ in range(200):
            sel=rng.integers(0,len(src),len(src)); ab,_=cv2.estimateAffinePartial2D(src[sel],dst[sel],method=cv2.LMEDS)
            boot.append(transform(query,np.vstack([ab,[0,0,1]])))
        spread=np.linalg.norm(np.array(boot)-transform(query,H),axis=2)
        inv=np.linalg.inv(H); capture_center=transform([center],inv)[0]
        reg=dict(capture=i+1,model='similarity source to capture1; no boundary fitting',matrix=H.tolist(),angle_degrees=float(np.degrees(np.arctan2(A[1,0],A[0,0]))),scale=float(np.linalg.norm(A[:,0])),matches=len(good),inliers=len(src),residual_rms_px=float(np.sqrt(np.mean(residual**2))),residual_p95_px=float(np.percentile(residual,95)),holdout_n=len(test),holdout_rms_px=float(np.sqrt(np.mean(hold**2))),holdout_p95_px=float(np.percentile(hold,95)),bootstrap_200_p95_corner_and_center_px=np.percentile(spread,95,axis=0).tolist(),card_center_in_capture_px=capture_center.tolist(),card_center_shift_from_capture1_px=(capture_center-center).tolist(),landmark_span_px=np.ptp(dst,axis=0).tolist())
        registrations.append(reg); write(OUT/f'capture-{i+1}/registration-landmarks.json',dict(source=src.tolist(),target=dst.tolist(),residual_px=residual.tolist()))
    # Card-centered axes follow reference fitted top side, origin provisional center.
    ex=corners[1]-corners[0]; ex=ex/np.linalg.norm(ex); ey=np.array([-ex[1],ex[0]])
    C=np.eye(3); C[:2,:2]=np.array([ex,ey]); C[:2,2]=-C[:2,:2]@center
    write(OUT/'registration.json',dict(reference_center_px=center.tolist(),reference_axes=C.tolist(),captures=registrations,warning='Print registration uncertainty does not establish absolute physical edge accuracy. Bootstrap is conditional on inlier landmarks; holdout includes model/scan mismatch.'))
    # Correspond physical sides by transformed side midpoint, never by layer ID.
    reference_mid=(corners+np.roll(corners,-1,axis=0))/2
    comparisons=[]
    for i in range(3):
        folder=OUT/f'capture-{i+1}'; candidates=json.loads((folder/'candidates.json').read_text())
        for mode_name,det in [('frozen',reports[i]['baseline']),('phase2',phases[i])]:
            for side in det['sides']:
                a=np.array(side['seed_start_pixels']); b=np.array(side['seed_end_pixels']); mid=transform([(a+b)/2],Hs[i])[0]; refidx=int(np.argmin(np.linalg.norm(reference_mid-mid,axis=1)))
                base=reports[0]['baseline']['sides'][refidx]; n=np.array(base['inward_normal']); line=np.array(base['line_abc']); ts=np.linspace(.25,.75,101); pts=corners[refidx]+ts[:,None]*(corners[(refidx+1)%4]-corners[refidx]); pts-=((pts@line[:2]+line[2])/(line[:2]@n))[:,None]*n
                for layer in side['candidate_layers']:
                    l=np.linalg.inv(Hs[i]).T@np.array(layer['line_abc']); offsets=-(pts@l[:2]+l[2])/(l[:2]@n)
                    feat=next(c['features'] for c in candidates if c['mode']==mode_name and c['side']==side['index'] and c['layer']['id']==layer['id'])
                    primary=feat['phases'][2]
                    comparisons.append(dict(capture=i+1,mode=mode_name,native_side=side['index'],card_side=refidx,layer=layer['id'],selected=layer['selected'],coverage=layer['coverage'],failures=layer['criterion_failures'],signed_inward_offset_from_capture1_selected_px=dict(median=float(np.median(offsets)),min=float(offsets.min()),max=float(offsets.max())),descriptor=primary.get('median_profile_descriptor'),features=primary.get('median_profile_features'),phase_descriptors=feat['subpixel_sensitivity']['median_profile_descriptors'],line_common=(np.linalg.inv(C@Hs[i]).T@np.array(layer['line_abc'])).tolist()))
    write(OUT/'comparison.json',comparisons)
    # Standalone SVG/Pillow rendering and additional common-location measurements.
    import runpy
    runpy.run_path(str(ROOT/'local_data/final-s21-acquisition-comparison-20261019-v2/finish.py'),init_globals={'OUTPUT':OUT})
    print(json.dumps(registrations,indent=2)); print('OUTPUT',OUT)
if __name__=='__main__': main()
