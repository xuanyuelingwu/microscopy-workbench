"""Generate clearly labelled synthetic OME-TIFF inputs; never experimental data."""
from pathlib import Path
import numpy as np
import tifffile
import core


def main():
    dest=Path(__file__).resolve().parent/"examples"
    dest.mkdir(exist_ok=True)
    rng=np.random.default_rng(20261019)
    nz,h,w=12,72,96
    z=np.array([0,.7,1.45,2.1,2.85,3.5,4.3,5.,5.75,6.4,7.1,7.9])
    zz,yy,xx=np.meshgrid(z,np.arange(h)*.2,np.arange(w)*.15,indexing="ij")
    a=50+2200*np.exp(-((xx-7.)**2/7+(yy-7.)**2/8+(zz-4.)**2/5))
    b=50+2600*np.exp(-((xx-8.)**2/3+(yy-6.)**2/4+(zz-4.5)**2/3))
    raw=np.clip(np.stack([a,b],axis=1)+rng.normal(0,3,(nz,2,h,w)),0,4095).round().astype(np.uint16)
    p=dest/"SYNTHETIC_nonuniform_Z.ome.tif"
    tifffile.imwrite(p,raw,ome=True,photometric="minisblack",metadata={
        "axes":"ZCYX","PhysicalSizeX":.15,"PhysicalSizeY":.2,"PhysicalSizeZ":.7,
        "PhysicalSizeXUnit":"µm","PhysicalSizeYUnit":"µm","PhysicalSizeZUnit":"µm",
        "Channel":{"Name":["Synthetic A","Synthetic B"]},
        "Plane":{"PositionZ":np.repeat(z,2).tolist(),"PositionZUnit":["µm"]*(nz*2)},
        "Description":"SYNTHETIC SOFTWARE DEMONSTRATION ONLY. Not acquired biological data. Seed 20261019."})
    channels=[{"index":0,"low":50,"high":3000,"gamma":.65,"background":50,"gate":150,"color":"#2774ff","opacity":.25},
              {"index":1,"low":50,"high":3000,"gamma":.65,"background":50,"gate":150,"color":"#ff4050","opacity":.45}]
    core.dump(dest/"volume_settings.json",{"schema":"microscopy-workbench/1","mode":"volume",
        "source_sha256":core.sha256(p),"channels":channels,"selection":{},
        "z_mode":"recorded","point_stride":2,"point_cap":50000,"surface_step":1,
        "example_type":"synthetic only; no biological interpretation"})
    n=14
    times=np.array([0,.7,1.8,3.4,5.,7.,9.1,11.6,14.6,17.2,20.1,23.4,27.,31.])
    movie=[]
    y,x=np.mgrid[:h,:w]
    for i in range(n):
        u=i/(n-1)
        green=50+1800*np.exp(-((x-(25+12*u))**2+(y-34)**2)/(2*(4+4*u)**2))
        red=50+2300*np.exp(-((x-46)**2+(y-(28+5*u))**2)/(2*(3+5*u)**2))
        movie.append(np.stack([green,red]))
    movie=np.clip(np.array(movie)+rng.normal(0,3,(n,2,h,w)),0,4095).round().astype(np.uint16)
    p=dest/"SYNTHETIC_irregular_time.ome.tif"
    tifffile.imwrite(p,movie,ome=True,photometric="minisblack",metadata={
        "axes":"TCYX","PhysicalSizeX":.15,"PhysicalSizeY":.2,
        "Channel":{"Name":["Synthetic A","Synthetic B"]},
        "Plane":{"DeltaT":np.repeat(times,2).tolist(),"DeltaTUnit":["s"]*(n*2)},
        "Description":"SYNTHETIC SOFTWARE DEMONSTRATION ONLY. Not acquired biological data. Seed 20261019."})
    core.dump(dest/"video_settings.json",{"schema":"microscopy-workbench/1","mode":"video",
        "source_sha256":core.sha256(p),"channels":channels,"selection":{},
        "start":2,"end":11,"zero_s":9.1,"roi":{"x":15,"y":12,"width":65,"height":47},
        "roi_reference_frame":12,"speed":3,"fps":30,"max_side":0,
        "timestamp":True,"scale_bar":True,
        "example_type":"synthetic only; no biological interpretation"})
    # Independent reference for the native-pixel overlap fractions.
    corrected=[np.maximum(raw[:,i].astype(float)-50,0) for i in range(2)]
    masks=[v>150 for v in corrected];overlap=masks[0]&masks[1]
    used=[float(v[overlap].sum()) for v in corrected]
    total=[float(v[m].sum()) for v,m in zip(corrected,masks)]
    core.dump(dest/"expected_results.json",{
        "synthetic":True,"seed":20261019,"z_um":z.tolist(),"times_s":times.tolist(),
        "overlap_percent":[100*used[0]/total[0],100*used[1]/total[1],100*sum(used)/sum(total)],
        "video_selected_native_frames_zero_based":list(range(2,12)),
        "video_first_relative_s":times[2]-9.1,"video_last_relative_s":times[11]-9.1})
    (dest/"README.txt").write_text(
        "All files in this directory are SYNTHETIC software demonstrations, not acquired biological data.\n"
        "Generate again: python generate_demo.py (fixed seed 20261019).\n"
        "Upload either OME-TIFF in the browser, or replay its saved configuration:\n"
        "python replay.py --source examples/SYNTHETIC_nonuniform_Z.ome.tif --settings examples/volume_settings.json --output demo_volume\n"
        "python replay.py --source examples/SYNTHETIC_irregular_time.ome.tif --settings examples/video_settings.json --output demo_video\n"
        "expected_results.json gives independently computed native-pixel overlap and recorded coordinates.\n",encoding="utf-8")
    print("Created two labelled synthetic OME-TIFF examples.")


if __name__=="__main__":main()
