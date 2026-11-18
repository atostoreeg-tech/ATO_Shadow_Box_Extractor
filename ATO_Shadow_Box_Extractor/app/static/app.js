/* ATO Extractor — plain JS, no build system or external CDN needed. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const stage = $('stage'), base = $('base'), overlay = $('overlay');
  const bc = base.getContext('2d'), oc = overlay.getContext('2d');
  const logoCanvas = document.createElement('canvas');
  const engraveCanvas = document.createElement('canvas');
  const state = { file:null, image:null, corners:[], tool:'corners', pointer:null,
                  cornerIndex:0, undo:null, autoRunning:false };
  let url = null;
  const notify = (text,type='') => {
    const el = $('alert'); el.className = `notice ${type}`; el.textContent = text;
  };
  const keyHeaders = () => $('accessKey').value ? {'X-ATO-Key':$('accessKey').value} : {};
  const requestError = async res => {
    let info = {};
    try { info = await res.json(); } catch (_) { /* ignored */ }
    throw new Error(typeof info.detail === 'string' ? info.detail : `Request failed (${res.status}).`);
  };
  const aspectFit = () => {
    if (!state.image) return;
    const scale = Math.min((stage.clientWidth - 10) / state.image.naturalWidth,
                           675 / state.image.naturalHeight, 1);
    for (const canvas of [base,overlay]) {
      canvas.style.width = `${Math.round(state.image.naturalWidth * scale)}px`;
      canvas.style.height = `${Math.round(state.image.naturalHeight * scale)}px`;
    }
  };
  const point = event => {
    const r = overlay.getBoundingClientRect();
    return [Math.min(overlay.width-1,Math.max(0,(event.clientX-r.left)*overlay.width/r.width)),
            Math.min(overlay.height-1,Math.max(0,(event.clientY-r.top)*overlay.height/r.height))];
  };
  const getCtx = tool => (tool.includes('engrave') ? engraveCanvas : logoCanvas).getContext('2d');
  const saveUndo = () => {
    const isE = state.tool.includes('engrave');
    const canvas = isE ? engraveCanvas : logoCanvas;
    state.undo = { engrave:isE, snapshot:canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height) };
  };
  const paint = (a,b,first=false) => {
    const ctx = getCtx(state.tool);
    const erase = state.tool.includes('erase');
    const engrave = state.tool.includes('engrave');
    const size = Number($('brush').value);
    ctx.save(); ctx.globalCompositeOperation = erase ? 'destination-out':'source-over';
    ctx.lineWidth = size;ctx.lineJoin='round';ctx.lineCap='round';
    ctx.strokeStyle = erase ? '#000' : (engrave ? '#27ddd1' : '#f2b33d');
    ctx.fillStyle = ctx.strokeStyle;
    if (first) {ctx.beginPath();ctx.arc(b[0],b[1],size/2,0,2*Math.PI);ctx.fill();}
    else {ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();}
    ctx.restore();
  };
  const redraw = () => {
    if (!state.image) return;
    oc.clearRect(0,0,overlay.width,overlay.height);
    oc.save(); oc.globalAlpha=.5;oc.drawImage(logoCanvas,0,0);oc.drawImage(engraveCanvas,0,0);oc.restore();
    const r = overlay.getBoundingClientRect();
    const scalar = Math.max(1,overlay.width/(r.width || 1));
    oc.lineWidth = 2 * scalar;
    oc.strokeStyle='#f4cf79';oc.fillStyle='rgba(230,179,72,.10)';
    if(state.corners.length===4) {
      oc.beginPath();state.corners.forEach(([x,y],i)=>i?oc.lineTo(x,y):oc.moveTo(x,y));oc.closePath();oc.fill();oc.stroke();
      state.corners.forEach(([x,y],i)=>{
        oc.beginPath();oc.arc(x,y,7*scalar,0,2*Math.PI);oc.fillStyle='#e7b348';oc.fill();
        oc.strokeStyle='#092033';oc.lineWidth=1.5*scalar;oc.stroke();
        oc.fillStyle='#102033';oc.font=`bold ${11*scalar}px sans-serif`;
        oc.textAlign='center';oc.textBaseline='middle';oc.fillText(String(i+1),x,y);
      });
    }
    if(state.pointer?.mode==='roi') {
      let {start,last}=state.pointer;
      oc.strokeStyle='#3ee0cf';oc.lineWidth=2.5*scalar;
      oc.setLineDash([9*scalar,5*scalar]);
      oc.strokeRect(start[0],start[1],last[0]-start[0],last[1]-start[1]);
      oc.setLineDash([]);
    }
  };
  const setTool = tool => {
    state.tool=tool;
    document.querySelectorAll('[data-tool]').forEach(el=>el.classList.toggle('active',el.dataset.tool===tool));
    $('toolLabel').textContent=tool.replaceAll('-',' ').toUpperCase();
    redraw();
  };
  const makeMasks = (w,h) => {
    for (const canvas of [logoCanvas,engraveCanvas]) {
      canvas.width = w;canvas.height=h;
    }
  };
  const chooseFile = async file => {
    if (!file) return;
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) {
      notify('Please select a JPG, PNG or WebP image.','error');return;
    }
    if(file.size>18*1024*1024){notify('Image exceeds 18 MB.','error');return;}
    const newUrl = URL.createObjectURL(file), img = new Image();
    img.onload = async () => {
      if(img.naturalWidth*img.naturalHeight>20_000_000){notify('Image is over 20 MP. Resize it before uploading.','error');URL.revokeObjectURL(newUrl);return;}
      if(url)URL.revokeObjectURL(url);url=newUrl;
      state.file=file;state.image=img;state.undo=null;
      base.width=overlay.width=img.naturalWidth;
      base.height=overlay.height=img.naturalHeight;
      makeMasks(img.naturalWidth,img.naturalHeight);
      bc.drawImage(img,0,0);
      const w=img.naturalWidth,h=img.naturalHeight,i=.04;
      state.corners=[[w*i,h*i],[w*(1-i),h*i],[w*(1-i),h*(1-i)],[w*i,h*(1-i)]];
      state.cornerIndex=0;stage.classList.remove('empty');$('emptyState').hidden=true;
      $('sourceInfo').textContent=`${file.name} · ${img.naturalWidth} × ${img.naturalHeight} px`;
      $('canvasInfo').textContent=`${img.naturalWidth} × ${img.naturalHeight} px · ${file.name}`;
      $('run').disabled=false;$('output').hidden=true;
      aspectFit();redraw();setTool('corners');
      notify('Photo loaded. Verify all four artwork corners, then select the raised logo.');
      await detectCorners(true);
    };
    img.onerror=()=>{URL.revokeObjectURL(newUrl);notify('Could not decode this image.','error');};
    img.src=newUrl;
  };
  const detectCorners = async silent => {
    if(!state.file)return;
    const data=new FormData();data.append('image',state.file);
    $('detectCorners').disabled=true;
    try{
      const response=await fetch('/api/corners',{method:'POST',headers:keyHeaders(),body:data});
      if(!response.ok)await requestError(response);
      const data=await response.json();state.corners=data.corners;
      state.cornerIndex=0;redraw();if(!silent)notify('Corner candidates detected. Drag to match the INSIDE printed artwork edges.');
    }catch(e){if(!silent)notify(e.message,'error');}
    finally{$('detectCorners').disabled=false;}
  };
  const autoSelect = async (a,b) => {
    if(!state.file||state.autoRunning)return;
    const box=[Math.round(Math.min(a[0],b[0])),Math.round(Math.min(a[1],b[1])),
               Math.round(Math.max(a[0],b[0])),Math.round(Math.max(a[1],b[1]))];
    if(box[2]-box[0]<15||box[3]-box[1]<15){notify('Draw a larger rectangle around the logo.','error');return;}
    state.autoRunning=true;notify('Auto Select: tracing potential foreground in selected rectangle...');
    const form=new FormData();form.append('image',state.file);form.append('rect_json',JSON.stringify(box));
    try{
      const response=await fetch('/api/segment',{method:'POST',headers:keyHeaders(),body:form});
      if(!response.ok)await requestError(response);
      const blob=await response.blob();
      const bmp=await createImageBitmap(blob);
      // Support undo even after the asynchronous request.
      state.tool='mask-add';saveUndo();
      logoCanvas.getContext('2d').drawImage(bmp,0,0);
      if(bmp.close)bmp.close();setTool('mask-add');
      notify('Auto Select applied. Paint missed shapes and erase unwanted areas. Verify internal holes.','ok');
    }catch(e){notify(e.message,'error');}
    finally{state.autoRunning=false;redraw();}
  };
  overlay.addEventListener('pointerdown',e=>{
    if(!state.image||state.autoRunning)return;
    e.preventDefault();overlay.setPointerCapture(e.pointerId);
    const p=point(e);
    if(state.tool==='corners') {
      const rect=overlay.getBoundingClientRect();
      const ratio=rect.width/overlay.width;
      let closest=0,distance=Infinity;
      state.corners.forEach((v,i)=>{
        const d=Math.hypot(v[0]-p[0],v[1]-p[1])*ratio;
        if(d<distance){distance=d;closest=i;}
      });
      const index=distance<35 ? closest : state.cornerIndex++ % 4;
      state.corners[index]=p;
      state.pointer={mode:'corner',index,last:p};
    }else if(state.tool==='roi'){
      state.pointer={mode:'roi',start:p,last:p};
    }else{
      saveUndo();state.pointer={mode:'paint',last:p};paint(p,p,true);
    }
    redraw();
  });
  overlay.addEventListener('pointermove',e=>{
    if(!state.pointer)return;
    e.preventDefault();const p=point(e),s=state.pointer;
    if(s.mode==='corner')state.corners[s.index]=p;
    else if(s.mode==='roi')s.last=p;
    else if(s.mode==='paint')paint(s.last,p);
    s.last=p;redraw();
  });
  const finishPointer=e=>{
    if(!state.pointer)return;
    let s=state.pointer;state.pointer=null;
    if(s.mode==='roi')autoSelect(s.start,s.last);
    else redraw();
  };
  overlay.addEventListener('pointerup',finishPointer);
  overlay.addEventListener('pointercancel',finishPointer);
  const canvasBlob = canvas => new Promise((resolve,reject)=>
    canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('Cannot export mask PNG.')),'image/png'));
  $('run').addEventListener('click',async()=>{
    if(!state.file)return;
    const width=Number($('widthMM').value);
    if(!Number.isFinite(width)||width<20||width>2500){notify('Enter the REAL artwork width in millimeters (20–2500 mm).','error');return;}
    const button=$('run');button.disabled=true;button.querySelector('span').textContent='Generating files...';
    try{
      const form=new FormData();
      form.append('image',state.file);
      form.append('logo_mask',await canvasBlob(logoCanvas),'logo-mask.png');
      form.append('engrave_mask',await canvasBlob(engraveCanvas),'engrave-mask.png');
      form.append('corners_json',JSON.stringify(state.corners));
      form.append('artwork_width_mm',String(width));
      form.append('dpi',$('dpi').value);
      form.append('inpaint_radius',$('radius').value);
      form.append('simplify_px',$('simplify').value);
      form.append('min_contour_area_px',$('minArea').value);
      notify('Processing source image and checking DXF contour geometry...');
      const response=await fetch('/api/process',{method:'POST',headers:keyHeaders(),body:form});
      if(!response.ok)await requestError(response);
      const result=await response.json();
      $('previewBG').src=result.files['Background.png'];
      $('previewSVG').src=result.files['Logo.svg'];
      for(const [id,key] of [['fileBG','Background.png'],['fileDXF','Logo.dxf'],
                             ['fileSVG','Logo.svg'],['fileZIP','ATO_Exports.zip']]){
        $(id).href=result.files[key];
      }
      const r=result.report;
      $('report').innerHTML='';
      const summary=document.createElement('p');
      summary.innerHTML=`<strong>Print:</strong> ${r.artwork_print_mm[0]} × ${r.artwork_print_mm[1]} mm, ${r.dpi} DPI · <strong>Logo:</strong> ${r.logo_bounds_mm[0]} × ${r.logo_bounds_mm[1]} mm · <strong>Contours:</strong> ${r.contour_counts.OUTER_CONTOURS} outer / ${r.contour_counts.INTERNAL_CUTOUTS} holes / ${r.contour_counts.ENGRAVE_DETAILS} engraved`;
      $('report').append(summary);
      const list=document.createElement('ul');
      for(const message of r.warnings){const li=document.createElement('li');li.textContent=message;list.append(li);}
      $('report').append(list);
      $('output').hidden=false;
      notify('Files created. Inspect the recovered background, internal holes and lettering before fabrication.','ok');
      $('output').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(e){notify(e.message,'error');}
    finally{button.disabled=false;button.querySelector('span').textContent='Generate production files';}
  });
  $('fileInput').addEventListener('change',e=>chooseFile(e.target.files[0]));
  for (const node of document.querySelectorAll('[data-tool]')) node.addEventListener('click',()=>setTool(node.dataset.tool));
  $('brush').addEventListener('input',()=>{$('brushValue').textContent=`${$('brush').value} px`;});
  $('detectCorners').addEventListener('click',()=>detectCorners(false));
  $('undo').addEventListener('click',()=>{
    if(!state.undo)return;
    const canvas=state.undo.engrave?engraveCanvas:logoCanvas;
    canvas.getContext('2d').putImageData(state.undo.snapshot,0,0);
    state.undo=null;redraw();notify('Last mask edit undone.');
  });
  $('clearMask').addEventListener('click',()=>{
    if(!state.image)return;
    for(const canvas of [logoCanvas,engraveCanvas])canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
    state.undo=null;redraw();notify('Both logo and engraving masks cleared.');
  });
  const drop=$('dropZone');
  drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('drag');});
  drop.addEventListener('dragleave',()=>drop.classList.remove('drag'));
  drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('drag');chooseFile(e.dataTransfer.files[0]);});
  window.addEventListener('resize',()=>{aspectFit();redraw();});
})();
