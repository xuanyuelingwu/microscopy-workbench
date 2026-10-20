"use strict";
const $=id=>document.getElementById(id);
const initialToken=new URLSearchParams(location.search).get("token");
if(initialToken){sessionStorage.setItem("mw_token",initialToken);history.replaceState(null,"",location.pathname);}
const TOKEN=sessionStorage.getItem("mw_token")||"";
const S={mode:"video",activeMode:"video",dataset:null,meta:null,channels:[],times:[],z:[],frame:0,start:0,end:1,zero:0,
 roi:null,roiRef:0,roiMode:"draw",image:null,frameSerial:0,jobs:new Map(),previewJob:null,
 previewSettings:null,dirty:false,loading:false,axisSelectors:new Map(),timelineDrag:null};
let frameTimer=null, pointer=null;
function error(message){$("error").hidden=false;$("error").querySelector("span").textContent=message;}
function clearError(){$("error").hidden=true;}
$("dismissError").onclick=clearError;
function safe(fn){return async function(){try{await fn.apply(this,arguments);}catch(e){if(e.name!=="AbortError")error(e.message||String(e));}};}
async function api(path,data){
 const opt={headers:{"X-Workbench-Token":TOKEN}};
 if(data!==undefined){opt.method="POST";opt.headers["Content-Type"]="application/json";opt.body=JSON.stringify(data);}
 const r=await fetch("/api/"+path,opt);
 const out=await r.json();if(!r.ok)throw new Error(out.error||r.statusText);return out;
}
function resultURL(id,file){
 return "/outputs/"+encodeURIComponent(id)+"/"+file.split("/").map(encodeURIComponent).join("/")+"?token="+encodeURIComponent(TOKEN);
}
function numberInput(id){const value=$(id).value;return value===""?null:Number(value);}
function bounds(v,lo,hi){return Math.max(lo,Math.min(hi,v));}
function clone(v){return JSON.parse(JSON.stringify(v));}
function enabledChannels(){return S.channels.filter(ch=>ch.enabled).map(ch=>{const c=Object.assign({},ch);delete c.enabled;return c;});}
function selection(){
 const out={};for(const [key,el] of S.axisSelectors)out[key]=Number(el.value);
 if(S.mode==="video" && S.meta && S.meta.has_time)out.T=S.frame;
 if(S.mode==="volume" && S.meta && S.meta.has_z)out.Z=S.frame;
 return out;
}
function config(){
 if(!S.dataset)throw new Error("请先选择源文件。");
 const channels=enabledChannels();
 if(!channels.length)throw new Error("请至少启用一个通道。");
 if(channels.length>(S.mode==="volume"?2:4))throw new Error("当前模式启用的通道过多。");
 return {channels:channels,selection:selection(),calibration:{x_um:numberInput("calX"),
 y_um:numberInput("calY"),z_step_um:numberInput("calZ")},time_interval_s:numberInput("calDt"),
 z_mode:$("zMode").value,roi:clone(S.roi),roi_reference_frame:S.roiRef,roi_reference_axis:S.mode==="volume"?"Z":"T",
 start:S.start,end:S.end,zero_s:S.zero,speed:Number($("speed").value),fps:Number($("fps").value),
 max_side:Number($("maxSide").value),timestamp:$("timestamp").checked,scale_bar:$("scaleBar").checked,
 point_stride:Number($("pointStride").value),point_cap:Number($("pointCap").value),
 surface_step:Number($("surfaceStep").value)};
}
function dirty(){
 S.dirty=true;$("lutStatus").textContent="参数已更改；当前帧将更新。已有视频 / 三维结果仍保留生成时的参数。";
 $("previewNotice").textContent="参数已更改；点击“生成 / 更新全视野视频”重新生成预览。";
 clearTimeout(frameTimer);frameTimer=setTimeout(()=>loadFrame().catch(e=>error(e.message)),320);
}
function mode(mode){
 const changed=mode!=="help" && mode!==S.activeMode;
 S.mode=mode;
 $("help").hidden=mode!=="help";$("workspace").hidden=mode==="help";
 $("videoTab").classList.toggle("active",mode==="video");$("volumeTab").classList.toggle("active",mode==="volume");$("helpTab").classList.toggle("active",mode==="help");
 $("videoPanel").hidden=mode!=="video";$("volumePanel").hidden=mode!=="volume";
 if(!S.meta || mode==="help")return;
 if(changed){S.frame=0;S.roiRef=0;S.roi={x:0,y:0,width:S.meta.sizes.X,height:S.meta.sizes.Y};}
 S.activeMode=mode;
 setupDimensions();setupFrameRange();
 $("dimensionNote").textContent=mode==="video"?"T 由时间轴控制；其余维度固定，不进行 Z 投影。":"Z 由层滑块控制；其余维度固定，通道一起按实测 Z 排序。";
 $("frameTitle").textContent=mode==="video"?"原生帧与观察范围":"原生 Z 层与重构范围";
 $("buildVolume").disabled=!S.meta.has_z;$("exportVideo").disabled=!S.meta.has_time;$("makePreview").disabled=!S.meta.has_time;
 if(mode==="video"&&!S.meta.has_time)error("此文件没有时间维度。可切换到三维模式（需要 Z 层扫）。");
 else if(mode==="volume"&&!S.meta.has_z)error("此文件没有 Z 层扫。时间序列不能直接当作三维结构。");
 else{clearError();loadAxes().then(loadFrame).catch(e=>error(e.message));}
}
$("videoTab").onclick=()=>mode("video");$("volumeTab").onclick=()=>mode("volume");$("helpTab").onclick=()=>mode("help");
function row(tbody,key,value){
 const tr=document.createElement("tr"),a=document.createElement("td"),b=document.createElement("td");a.textContent=key;b.textContent=value;tr.append(a,b);tbody.append(tr);
}
async function acceptSource(out){
 S.dataset=out.id;S.meta=out.metadata;S.sourcePath=out.source_path;S.image=null;S.frame=0;S.roiRef=0;S.previewSettings=null;
 const m=S.meta;S.roi={x:0,y:0,width:m.sizes.X,height:m.sizes.Y};
 $("metadata").hidden=false;$("sourceName").textContent=m.name;$("metaRows").replaceChildren();
 row($("metaRows"),"维度",Object.entries(m.sizes).map(([k,v])=>k+"="+v).join(" · "));
 row($("metaRows"),"像素类型",m.dtype+(m.significant_bits?" · "+m.significant_bits+" 有效位":""));
 row($("metaRows"),"大小",(m.size_bytes/1024/1024).toFixed(1)+" MB");
 row($("metaRows"),"XY / µm",(m.calibration.x_um===null?"未校准":m.calibration.x_um.toFixed(6))+" / "+(m.calibration.y_um===null?"未校准":m.calibration.y_um.toFixed(6)));
 row($("metaRows"),"名义 Z / µm",m.calibration.z_step_um===null?"无 / 未校准":m.calibration.z_step_um);
 $("sourceWarning").textContent=m.warnings.join(" ");
 $("uploadMessage").textContent="已打开："+out.source_path;
 for(const id of ["dimensionSection","channelSection","advancedSection","editor"])$(id).hidden=false;
 $("empty").hidden=true;$("sceneSection").hidden=true;$("fullVideo").hidden=true;$("previewActions").hidden=true;
 $("fullVideo").pause();$("fullVideo").removeAttribute("src");
 $("calX").value="";$("calY").value="";$("calZ").value="";$("calDt").value="";$("zMode").value="auto";
 S.times=m.times_s||[];S.z=m.z_um||[];
 S.start=0;S.end=Math.max(1,m.sizes.T-1||1);S.zero=S.times[0]||0;
 const candidates=m.channels.filter(ch=>!/\bTD\b|transmit|brightfield/i.test(ch.name));
 const chosen=(candidates.length<=2?candidates:[candidates[0],candidates[candidates.length-1]]).map(ch=>ch.index);
 S.channels=m.channels.map(ch=>({index:ch.index,name:ch.name,enabled:chosen.includes(ch.index),
 color:ch.color,low:ch.low,high:ch.high,gamma:.7,background:ch.background,gate:150,opacity:.35}));
 setupChannels();mode(m.has_time?"video":m.has_z?"volume":S.mode);
 syncROI();updateTimeline();S.dirty=false;
 if(m.has_time){
  await loadAxes();await loadFrame();
  // Initial full-field movie is a snapshot of these fixed display settings.
  await startJob("preview",true);
 }
}
async function uploadFile(file){
 if(!file)return;
 clearError();$("uploadProgress").hidden=false;$("uploadProgress").value=0;$("uploadMessage").textContent="上传到本机缓存…";
 $("sourceFile").disabled=true;
 try{
  const out=await new Promise((resolve,reject)=>{
   const xhr=new XMLHttpRequest();xhr.open("POST","/api/upload");xhr.setRequestHeader("X-Workbench-Token",TOKEN);xhr.setRequestHeader("X-Filename",encodeURIComponent(file.name));
   xhr.upload.onprogress=e=>{if(e.lengthComputable)$("uploadProgress").value=e.loaded/e.total*100;};
   xhr.upload.onload=()=>{$("uploadMessage").textContent="正在解析文件元数据…";};
   xhr.onerror=()=>reject(new Error("本机上传失败，请确认 Python 服务仍在运行。"));
   xhr.onload=()=>{try{const data=JSON.parse(xhr.responseText);if(xhr.status>=400)reject(new Error(data.error));else resolve(data);}catch(e){reject(e);}};
   xhr.send(file);
  });
  await acceptSource(out);
 }finally{$("sourceFile").disabled=false;$("uploadProgress").hidden=true;}
}
$("sourceFile").onchange=safe(async e=>uploadFile(e.target.files[0]));
$("openPath").onclick=safe(async()=>{
 clearError();$("openPath").disabled=true;$("uploadMessage").textContent="正在直接读取本机文件…";
 try{await acceptSource(await api("open-path",{path:$("sourcePath").value}));}finally{$("openPath").disabled=false;}
});
function setupDimensions(){
 $("dimensions").replaceChildren();S.axisSelectors.clear();
 const varying=S.mode==="video"?"T":"Z";
 for(const key of S.meta.axes){
  if(key===varying)continue;
  const wrap=document.createElement("label");wrap.className="dimension-row";wrap.append(document.createTextNode(key+" 固定索引"));
  const sel=document.createElement("select");sel.setAttribute("aria-label",key+" 固定索引");
  for(let i=0;i<S.meta.sizes[key];i++){const o=document.createElement("option");o.value=i;o.textContent=String(i+1)+" / "+S.meta.sizes[key];sel.append(o);}
  sel.onchange=safe(async()=>{S.dirty=true;await loadAxes();await loadFrame();$("previewNotice").textContent="固定维度已更改，请重新生成全视野预览。";});
  S.axisSelectors.set(key,sel);wrap.append(sel);$("dimensions").append(wrap);
 }
 if(!S.axisSelectors.size){const p=document.createElement("p");p.className="small muted";p.textContent="没有额外需要固定的采集维度。";$("dimensions").append(p);}
}
function channelNumber(ch,key,label,step){
 const lab=document.createElement("label");lab.textContent=label;
 const input=document.createElement("input");input.type="number";input.step=step||"any";input.value=ch[key];input.setAttribute("aria-label",ch.name+" "+label);
 input.oninput=()=>{ch[key]=Number(input.value);dirty();};lab.append(input);return lab;
}
function setupChannels(){
 $("channels").replaceChildren();
 S.channels.forEach(ch=>{
  const box=document.createElement("div");box.className="channel";
  const head=document.createElement("div");head.className="channel-header";
  const label=document.createElement("label"),on=document.createElement("input");on.type="checkbox";on.checked=ch.enabled;on.setAttribute("aria-label","启用 "+ch.name);
  on.onchange=()=>{ch.enabled=on.checked;dirty();};
  label.append(on,document.createTextNode(ch.name));const col=document.createElement("input");col.type="color";col.value=ch.color;col.setAttribute("aria-label",ch.name+" 显示颜色");
  col.oninput=()=>{ch.color=col.value;dirty();};head.append(label,col);box.append(head);
  const pair=document.createElement("div");pair.className="pair";pair.append(channelNumber(ch,"low","显示下限"),channelNumber(ch,"high","显示上限"));box.append(pair);
  box.append(channelNumber(ch,"gamma","显示 gamma"));
  const d=document.createElement("details");d.open=S.mode==="volume";const sum=document.createElement("summary");sum.textContent="三维阈值与透明度";d.append(sum);
  const p=document.createElement("div");p.className="pair";p.append(channelNumber(ch,"background","背景 / a.u."),channelNumber(ch,"gate","背景以上阈值"));d.append(p);
  const op=document.createElement("label");op.textContent="初始不透明度";const range=document.createElement("input");range.type="range";range.min=0;range.max=1;range.step=.01;range.value=ch.opacity;
  range.setAttribute("aria-label",ch.name+" 初始不透明度");range.oninput=()=>{ch.opacity=Number(range.value);};op.append(range);d.append(op);
  const note=document.createElement("p");note.className="small muted";note.textContent="生成后可在三维视图中即时分别调整透明度。";d.append(note);box.append(d);$("channels").append(box);
 });
}
function setupFrameRange(){
 const n=S.mode==="video"?S.meta.sizes.T||1:S.meta.sizes.Z||1;
 $("frameSlider").max=n-1;$("frameNumber").max=n;S.frame=bounds(S.frame,0,n-1);
 $("frameSlider").value=S.frame;$("frameNumber").value=S.frame+1;
}
async function loadAxes(){
 if(!S.dataset)return;
 const out=await api("axes",{dataset:S.dataset,config:config()});
 if(out.times_s){
  S.times=out.times_s;S.end=bounds(S.end,1,S.times.length-1);S.start=bounds(S.start,0,S.end-1);
  $("timeSource").textContent="时间记录："+out.time_source+"；参考首个启用通道。源首帧 "+S.times[0].toFixed(3)+" s。";
 }
 if(out.z_um){S.z=out.z_um;$("zSource").textContent="Z 坐标："+out.z_source+"；"+out.z_um.length+" 层，层中心跨度 "+out.z_um.at(-1).toFixed(3)+" µm。"+(out.warnings||[]).join(" ");}
 updateTimeline();return out;
}
async function loadFrame(){
 if(!S.dataset||S.mode==="help")return;
 const serial=++S.frameSerial;
 $("frameStatus").textContent="读取原生帧…";
 const cfg=config();
 const r=await fetch("/api/frame",{method:"POST",headers:{"X-Workbench-Token":TOKEN,"Content-Type":"application/json"},
 body:JSON.stringify({dataset:S.dataset,config:cfg})});
 if(!r.ok){const o=await r.json();throw new Error(o.error);}
 const blob=await r.blob();const im=await createImageBitmap(blob);
 if(serial!==S.frameSerial){im.close();return;}
 if(S.image)S.image.close();S.image=im;
 const canvas=$("frameCanvas");canvas.width=im.width;canvas.height=im.height;fitCanvas();paint();
 $("frameSlider").value=S.frame;$("frameNumber").value=S.frame+1;
 if(S.mode==="video"&&S.times.length){
  $("frameTime").textContent="t = "+(S.times[S.frame]-S.zero).toFixed(2)+" s · 源 "+S.times[S.frame].toFixed(3)+" s";
 }else{$("frameTime").textContent="原始 Z 索引 "+(S.frame+1)+" / "+(S.meta.sizes.Z||1);}
 $("frameStatus").textContent=im.width+" × "+im.height+" 原生像素";
 $("lutStatus").textContent="当前帧已应用固定显示参数；导出时全片使用相同 LUT。";
 updateTimeline();syncROI();
}
function fitCanvas(){
 if(!S.image)return;
 const avail=$("frameCanvas").parentElement.clientWidth;
 const width=Math.max(1,Math.min(avail,window.innerHeight*.68*S.image.width/S.image.height));
 $("frameCanvas").style.width=width+"px";$("frameCanvas").style.height=width*S.image.height/S.image.width+"px";
}
window.addEventListener("resize",()=>{fitCanvas();updateTimeline();});
new ResizeObserver(fitCanvas).observe($("frameCanvas").parentElement);
function goFrame(n){
 const max=Number($("frameSlider").max);S.frame=bounds(Math.round(n),0,max);$("frameSlider").value=S.frame;$("frameNumber").value=S.frame+1;
 clearTimeout(frameTimer);frameTimer=setTimeout(()=>loadFrame().catch(e=>error(e.message)),65);
 updateTimeline();
}
$("frameSlider").oninput=e=>goFrame(Number(e.target.value));
$("frameNumber").oninput=e=>{if(e.target.value!=="")goFrame(Number(e.target.value)-1);};
$("frameNumber").onchange=e=>goFrame(Number(e.target.value)-1);
$("prevFrame").onclick=()=>goFrame(S.frame-1);$("nextFrame").onclick=()=>goFrame(S.frame+1);
$("applyDisplay").onclick=safe(async()=>{await loadAxes();await loadFrame();});
$("applyCalibration").onclick=safe(async()=>{S.dirty=true;await loadAxes();await loadFrame();});
function paint(){
 if(!S.image)return;
 const c=$("frameCanvas"),ctx=c.getContext("2d"),r=S.roi;
 ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(S.image,0,0);
 if(r){
  ctx.fillStyle="rgba(0,0,0,0.38)";ctx.beginPath();ctx.rect(0,0,c.width,c.height);ctx.rect(r.x,r.y,r.width,r.height);ctx.fill("evenodd");
  const scale=c.width/Math.max(1,c.getBoundingClientRect().width);
  ctx.strokeStyle="#ffdf52";ctx.lineWidth=1.5*scale;ctx.strokeRect(r.x,r.y,r.width,r.height);
  if(S.roiMode==="move"){
   const sz=7*scale;ctx.fillStyle="#ffdf52";
   for(const [x,y]of [[r.x,r.y],[r.x+r.width,r.y],[r.x,r.y+r.height],[r.x+r.width,r.y+r.height]])ctx.fillRect(x-sz/2,y-sz/2,sz,sz);
  }
  const crop=$("cropCanvas"),scale2=Math.min(1,400/r.width,400/r.height);crop.width=Math.max(1,Math.round(r.width*scale2));crop.height=Math.max(1,Math.round(r.height*scale2));
  const cc=crop.getContext("2d");cc.imageSmoothingEnabled=false;cc.drawImage(S.image,r.x,r.y,r.width,r.height,0,0,crop.width,crop.height);
 }
}
function syncROI(){
 if(!S.roi)return;
 for(const [id,key]of [["roiX","x"],["roiY","y"],["roiW","width"],["roiH","height"]])$(id).value=S.roi[key];
 $("roiInfo").textContent="x="+S.roi.x+", y="+S.roi.y+"；"+S.roi.width+" × "+S.roi.height+" px";
 $("roiReference").textContent="框选参考："+(S.mode==="video"?"源第 "+(S.roiRef+1)+" 帧":"原始第 "+(S.roiRef+1)+" 个 Z 层")+"。坐标从 0 开始。";
}
function roiMode(m){S.roiMode=m;$("drawROI").classList.toggle("active",m==="draw");$("moveROI").classList.toggle("active",m==="move");$("frameCanvas").style.cursor=m==="draw"?"crosshair":"move";paint();}
$("drawROI").onclick=()=>roiMode("draw");$("moveROI").onclick=()=>roiMode("move");
$("resetROI").onclick=()=>{if(!S.meta)return;S.roi={x:0,y:0,width:S.meta.sizes.X,height:S.meta.sizes.Y};S.roiRef=S.frame;roiMode("draw");syncROI();paint();};
$("applyROI").onclick=safe(async()=>{
 if(!S.meta)return;
 const r={x:Number($("roiX").value),y:Number($("roiY").value),width:Number($("roiW").value),height:Number($("roiH").value)};
 if(!Object.values(r).every(Number.isInteger)||r.x<0||r.y<0||r.width<1||r.height<1||r.x+r.width>S.meta.sizes.X||r.y+r.height>S.meta.sizes.Y)throw new Error("ROI 坐标需为有效原生整数像素，不能超出图像。");
 S.roi=r;S.roiRef=S.frame;syncROI();paint();
});
function point(e,canvas){
 const r=canvas.getBoundingClientRect();
 return {x:bounds(Math.round((e.clientX-r.left)/r.width*canvas.width),0,canvas.width),
 y:bounds(Math.round((e.clientY-r.top)/r.height*canvas.height),0,canvas.height)};
}
$("frameCanvas").addEventListener("pointerdown",e=>{
 if(!S.image)return;
 const canvas=e.currentTarget,p=point(e,canvas),r=S.roi;canvas.setPointerCapture(e.pointerId);
 let action="draw",corner="";
 if(S.roiMode==="move"&&r){
  const tol=12*canvas.width/canvas.getBoundingClientRect().width;
  for(const [name,x,y]of [["nw",r.x,r.y],["ne",r.x+r.width,r.y],["sw",r.x,r.y+r.height],["se",r.x+r.width,r.y+r.height]]){
   if(Math.abs(p.x-x)<tol&&Math.abs(p.y-y)<tol){action="resize";corner=name;break;}
  }
  if(!corner&&p.x>=r.x&&p.x<=r.x+r.width&&p.y>=r.y&&p.y<=r.y+r.height)action="move";
 }
 pointer={start:p,original:clone(r),action:action,corner:corner};
});
$("frameCanvas").addEventListener("pointermove",e=>{
 if(!pointer||!S.image)return;
 const p=point(e,e.currentTarget),o=pointer.original,a=pointer.start,W=S.meta.sizes.X,H=S.meta.sizes.Y;
 let r;
 if(pointer.action==="move"){
  r={x:bounds(o.x+p.x-a.x,0,W-o.width),y:bounds(o.y+p.y-a.y,0,H-o.height),width:o.width,height:o.height};
 }else if(pointer.action==="resize"){
  const left=pointer.corner.includes("w")?p.x:o.x,right=pointer.corner.includes("e")?p.x:o.x+o.width;
  const top=pointer.corner.includes("n")?p.y:o.y,bottom=pointer.corner.includes("s")?p.y:o.y+o.height;
  r={x:Math.min(left,right),y:Math.min(top,bottom),width:Math.max(1,Math.abs(right-left)),height:Math.max(1,Math.abs(bottom-top))};
 }else{
  r={x:Math.min(a.x,p.x),y:Math.min(a.y,p.y),width:Math.max(1,Math.abs(p.x-a.x)),height:Math.max(1,Math.abs(p.y-a.y))};
 }
 r.x=bounds(r.x,0,W-1);r.y=bounds(r.y,0,H-1);r.width=bounds(r.width,1,W-r.x);r.height=bounds(r.height,1,H-r.y);
 S.roi=r;S.roiRef=S.frame;paint();syncROI();
});
function endPointer(e){if(!pointer)return;pointer=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);syncROI();paint();}
$("frameCanvas").addEventListener("pointerup",endPointer);$("frameCanvas").addEventListener("pointercancel",endPointer);
function timeX(t,width){return 30+(t-S.times[0])/(S.times.at(-1)-S.times[0])*(width-60);}
function nearestFrame(x,width){
 const t=S.times[0]+bounds((x-30)/(width-60),0,1)*(S.times.at(-1)-S.times[0]);
 let best=0;for(let i=1;i<S.times.length;i++)if(Math.abs(S.times[i]-t)<Math.abs(S.times[best]-t))best=i;return best;
}
function updateTimeline(){
 if(!S.times.length)return;
 const n=S.times.length;S.start=bounds(S.start,0,n-2);S.end=bounds(S.end,S.start+1,n-1);
 $("startFrame").value=S.start+1;$("startFrame").max=n-1;$("endFrame").value=S.end+1;$("endFrame").max=n;
 $("startRange").max=n-2;$("startRange").value=S.start;$("endRange").max=n-1;$("endRange").value=S.end;
 $("zeroTime").value=String(S.zero);
 const a=S.times[S.start]-S.zero,b=S.times[S.end]-S.zero;
 $("intervalSummary").textContent="选定 "+(S.end-S.start+1)+" 个原生帧；相对时间 "+a.toFixed(2)+" 至 "+b.toFixed(2)+" s；观测跨度 "+(b-a).toFixed(3)+" s（未含末帧显示停留）。";
 const c=$("timeline"),ctx=c.getContext("2d"),w=c.width,h=c.height;
 ctx.clearRect(0,0,w,h);ctx.fillStyle="#f4f6f7";ctx.fillRect(30,26,w-60,35);
 const x0=timeX(S.times[S.start],w),x1=timeX(S.times[S.end],w);
 ctx.fillStyle="#d2e1e7";ctx.fillRect(x0,26,x1-x0,35);
 ctx.strokeStyle="#aab6bc";ctx.lineWidth=1;
 const skip=Math.max(1,Math.ceil(n/200));for(let i=0;i<n;i+=skip){const x=timeX(S.times[i],w);ctx.beginPath();ctx.moveTo(x,44);ctx.lineTo(x,57);ctx.stroke();}
 ctx.fillStyle="#254d61";ctx.fillRect(x0-5,23,10,41);ctx.fillRect(x1-5,23,10,41);
 const zero=timeX(S.zero,w);if(zero>=30&&zero<=w-30){ctx.strokeStyle="#9b3939";ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(zero,12);ctx.lineTo(zero,71);ctx.stroke();}
 const cur=timeX(S.times[bounds(S.frame,0,n-1)],w);ctx.fillStyle="#111";ctx.beginPath();ctx.moveTo(cur,18);ctx.lineTo(cur-6,10);ctx.lineTo(cur+6,10);ctx.fill();
 ctx.font="14px Arial";ctx.fillStyle="#46555e";ctx.textAlign="left";ctx.fillText((S.times[0]-S.zero).toFixed(2)+" s",30,88);ctx.textAlign="right";ctx.fillText((S.times.at(-1)-S.zero).toFixed(2)+" s",w-30,88);
 ctx.textAlign="center";ctx.fillText("原始采集时间轴",w/2,88);
}
function changeRange(which,value){
 const n=S.times.length;if(n<2)return;value=Math.round(value);
 if(which==="start")S.start=bounds(value,0,S.end-1);else S.end=bounds(value,S.start+1,n-1);
 updateTimeline();
}
function readTimeInputs(){
 const a=Number($("startFrame").value)-1,b=Number($("endFrame").value)-1,z=Number($("zeroTime").value);
 if(!Number.isInteger(a)||!Number.isInteger(b)||a<0||b>=S.times.length||a>=b||!Number.isFinite(z))throw new Error("请设置有效的起止帧（至少两帧）与计时零点。");
 S.start=a;S.end=b;S.zero=z;updateTimeline();
}
$("startFrame").onchange=e=>changeRange("start",Number(e.target.value)-1);$("endFrame").onchange=e=>changeRange("end",Number(e.target.value)-1);
$("startRange").oninput=e=>changeRange("start",Number(e.target.value));$("endRange").oninput=e=>changeRange("end",Number(e.target.value));
$("setStart").onclick=()=>changeRange("start",S.frame);$("setEnd").onclick=()=>changeRange("end",S.frame);
$("zeroTime").onchange=e=>{if(Number.isFinite(Number(e.target.value))){S.zero=Number(e.target.value);updateTimeline();loadFrame().catch(e=>error(e.message));}};
$("setZero").onclick=()=>{if(!S.times.length)return;S.zero=S.times[S.frame];updateTimeline();loadFrame().catch(e=>error(e.message));};
$("zeroFirst").onclick=()=>{if(!S.times.length)return;S.zero=S.times[0];updateTimeline();loadFrame().catch(e=>error(e.message));};
$("timeline").addEventListener("pointerdown",e=>{
 if(S.times.length<2)return;
 const c=e.currentTarget,p=point(e,c),tol=15*c.width/c.getBoundingClientRect().width;
 const x0=timeX(S.times[S.start],c.width),x1=timeX(S.times[S.end],c.width);
 S.timelineDrag=Math.abs(p.x-x0)<tol?"start":Math.abs(p.x-x1)<tol?"end":"seek";
 c.setPointerCapture(e.pointerId);
 if(S.timelineDrag==="seek")goFrame(nearestFrame(p.x,c.width));
});
$("timeline").addEventListener("pointermove",e=>{
 if(!S.timelineDrag)return;
 const c=e.currentTarget,p=point(e,c),i=nearestFrame(p.x,c.width);
 if(S.timelineDrag==="seek")goFrame(i);else changeRange(S.timelineDrag,i);
});
$("timeline").addEventListener("pointerup",e=>{S.timelineDrag=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);});
async function startJob(type,automatic){
 if(!S.dataset)return;
 if(!automatic)clearError();
 if(type==="video"){
  readTimeInputs();
 }
 const cfg=config(),dataset=S.dataset;
 if(type==="volume"&&cfg.channels.length>2)throw new Error("三维每次启用一或两个通道。");
 const job=await api("jobs",{dataset:dataset,mode:type,config:cfg});
 S.jobs.set(job.id,{job:job,dataset:dataset,handled:false});
 if(type==="preview"){$("previewNotice").textContent="正在生成全视野预览。处理期间仍可使用上方原生帧和裁剪框。";S.previewJob=job.id;}
 $("jobSection").hidden=false;showJobs();pollJob(job.id);
 return job;
}
function showJobs(){
 const active=[...S.jobs.values()].filter(v=>["running","queued"].includes(v.job.status));
 if(!active.length){$("cancelJob").hidden=true;return;}
 const v=active.find(x=>x.job.status==="running")||active[0];$("cancelJob").hidden=false;$("cancelJob").dataset.job=v.job.id;
 $("jobProgress").value=v.job.progress;$("jobMessage").textContent=v.job.message+" · "+v.job.progress.toFixed(0)+"%"+(active.length>1?"（另有 "+(active.length-1)+" 个任务等待）":"");
}
async function pollJob(id){
 const v=S.jobs.get(id);if(!v)return;
 try{
  v.job=await api("jobs/"+id);showJobs();
  if(["queued","running"].includes(v.job.status)){setTimeout(()=>pollJob(id),900);return;}
  if(v.handled)return;v.handled=true;
  $("jobProgress").value=v.job.progress;$("jobMessage").textContent=v.job.message;
  if(v.job.status==="done"){await completed(v);S.dirty=false;}
  else if(v.job.status==="error")error(v.job.message+"；日志："+v.job.folder+"\\error.log");
  else if(v.job.status==="cancelled"){$("jobMessage").textContent="任务已取消。";}
 }catch(e){error("读取任务状态失败："+e.message+"。请确认本地服务仍在运行。");}
}
function addLink(box,label,url,download){
 const a=document.createElement("a");a.textContent=label;a.href=url;
 if(download)a.download="";else{a.target="_blank";a.rel="noopener";}box.append(a);return a;
}
async function completed(v){
 const j=v.job,r=j.result,card=document.createElement("div");card.className="result";
 const h=document.createElement("h3");h.textContent=(j.mode==="volume"?"两种三维重构":j.mode==="preview"?"完整时间序列 · 全视野预览":"选定区间 · 全视野与局部视频")+" · "+j.id;card.append(h);
 const links=document.createElement("div");links.className="links";
 addLink(links,"下载完整结果 ZIP",resultURL(j.id,r.bundle),true);
 if(j.mode==="volume"){
  addLink(links,"打开两种三维视图",resultURL(j.id,"viewer.html"),false);
  addLink(links,"原始 OME-TIFF",resultURL(j.id,"native_stack.ome.tif"),true);
  if(r.overlap)addLink(links,"三项共现百分比 CSV",resultURL(j.id,"native_overlap.csv"),true);
 }else{
  for(const [key,m]of Object.entries(r.media)){
   const title=key==="full"?"全视野":"局部";addLink(links,title+" MP4",resultURL(j.id,m.mp4),true);addLink(links,title+" GIF",resultURL(j.id,m.gif),true);
  }
  addLink(links,"原始帧与时间映射",resultURL(j.id,"native_frame_timing.csv"),true);
 }
 addLink(links,"复现参数 JSON",resultURL(j.id,"settings.json"),true);addLink(links,"处理方法",resultURL(j.id,"METHODS.txt"),false);
 card.append(links);
 const p=document.createElement("p");p.className="path";p.textContent=j.folder;card.append(p);
 const open=document.createElement("button");open.textContent="打开本机输出文件夹";open.onclick=safe(async()=>api("open-output",{id:j.id}));card.append(open);
 const detail=document.createElement("details"),summary=document.createElement("summary");summary.textContent="查看全部配套文件";detail.append(summary);
 const ul=document.createElement("div");ul.className="links";for(const file of r.files)addLink(ul,file,resultURL(j.id,file),true);detail.append(ul);card.append(detail);
 $("results").prepend(card);$("resultsSection").hidden=false;
 if(v.dataset!==S.dataset)return;
 if(j.mode==="preview"){
  $("fullVideo").src=resultURL(j.id,"full.mp4");$("fullVideo").hidden=false;$("previewActions").hidden=false;
  const t=r.timing_summary;$("previewSpeed").textContent="实际播放 "+t.effective_speed.toFixed(3)+"×；全部原生帧保留。";
  $("previewNotice").textContent="完整时间段预览已生成。可在下方播放器定位，再载入上方原生帧；最终导出使用当前时间区间、零点和裁剪框。";
  const response=await fetch(resultURL(j.id,"settings.json"));S.previewSettings=await response.json();
 }else if(j.mode==="volume"){
  $("sceneSection").hidden=false;$("sceneFrame").src=resultURL(j.id,r.viewer);$("openViewer").href=resultURL(j.id,r.viewer);
 }
}
$("makePreview").onclick=safe(async()=>{await loadAxes();await startJob("preview");});
$("exportVideo").onclick=safe(async()=>{readTimeInputs();await loadAxes();await startJob("video");});
$("buildVolume").onclick=safe(async()=>{await loadAxes();await startJob("volume");});
$("cancelJob").onclick=safe(async()=>{const id=$("cancelJob").dataset.job;if(id)await api("cancel",{id:id});});
$("useVideoFrame").onclick=()=>{
 if(!S.previewSettings)return;
 const row=S.previewSettings.timing.rows.find(r=>$("fullVideo").currentTime<(r.mp4_first_frame+r.mp4_repetitions)/S.previewSettings.timing.fps)||S.previewSettings.timing.rows.at(-1);
 goFrame(row.source_T_zero_based);
};
document.addEventListener("keydown",e=>{
 if(["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName))return;
 if(e.key==="ArrowLeft"){e.preventDefault();goFrame(S.frame-1);}if(e.key==="ArrowRight"){e.preventDefault();goFrame(S.frame+1);}
});
safe(async()=>{
 const status=await api("status");$("connection").textContent="本地服务已连接 · v"+status.version;
 $("outputRoot").textContent=status.data_root+"\\outputs";
 if(status.jobs.length){
  for(const job of status.jobs){S.jobs.set(job.id,{job:job,dataset:null,handled:false});pollJob(job.id);}
 }
})();
