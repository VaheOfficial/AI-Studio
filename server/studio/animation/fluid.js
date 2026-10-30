/* Fixed-step dye transport with checkpointed, history-independent seeking. */
(() => {
  window.AnimationFluid=({color})=>{
    const caches=new Map();
    function create(q,p,box){
      const w={low:48,medium:80,high:128}[q.resolution||'medium'],h=Math.max(24,Math.min(128,Math.round(w*box.h/box.w))),n=w*h;
      const empty=()=>Array.from({length:6},()=>new Float32Array(n));
      const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
      const emitters=q.emitters.map(e=>({...e,rgb:[1,3,5].map(i=>parseInt(color(e.color,p).slice(i,i+2),16)/255)}));
      const snapshots=new Map([[0,empty()]]),scratch=empty(),pressure=new Float32Array(n),next=new Float32Array(n),div=new Float32Array(n),curl=new Float32Array(n);
      function sample(field,x,y){x=Math.max(0,Math.min(w-1.001,x));y=Math.max(0,Math.min(h-1.001,y));const ix=Math.floor(x),iy=Math.floor(y),fx=x-ix,fy=y-iy,i=iy*w+ix;return (field[i]*(1-fx)+field[i+1]*fx)*(1-fy)+(field[i+w]*(1-fx)+field[i+w+1]*fx)*fy;}
      function advance(fields,step){
        const t=step/30-(q.pre_roll??0),[u,v,d,r,g,b]=fields;
        for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){const i=y*w+x;curl[i]=(v[i+1]-v[i-1]-u[i+w]+u[i-w])*.5;}
        for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){
          const i=y*w+x,gx=Math.abs(curl[i+1])-Math.abs(curl[i-1]),gy=Math.abs(curl[i+w])-Math.abs(curl[i-w]),length=Math.hypot(gx,gy)+1e-5;
          u[i]+=gy/length*curl[i]*.08;v[i]-=gx/length*curl[i]*.08;
        }
        for(const [index,e] of emitters.entries()){
          if(t<0?(e.start??0)>0:t<(e.start??0)||t>=(e.end??120))continue;
          const ex=(e.x+Math.sin(t*.9+index*2)*(e.wander??.02))*w,ey=(e.y+Math.cos(t*.7+index*3)*(e.wander??.02))*h,radius=(e.radius??.04)*Math.min(w,h),angle=(e.direction??-90)*Math.PI/180;
          for(let y=Math.max(1,Math.floor(ey-radius*3));y<Math.min(h-1,ey+radius*3);y++)for(let x=Math.max(1,Math.floor(ex-radius*3));x<Math.min(w-1,ex+radius*3);x++){
            const i=y*w+x,a=Math.exp(-((x-ex)**2+(y-ey)**2)/(radius*radius))* (e.strength??1)/30;
            d[i]+=a*3;r[i]+=a*3*e.rgb[0];g[i]+=a*3*e.rgb[1];b[i]+=a*3*e.rgb[2];u[i]+=Math.cos(angle)*a*18;v[i]+=Math.sin(angle)*a*18;
          }
        }
        for(let k=0;k<6;k++){
          const output=scratch[k],input=fields[k];output.fill(0);
          for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){const i=y*w+x;output[i]=sample(input,x-u[i]/30,y-v[i]/30)*(k<2?.994:.9985);}
        }
        for(let k=0;k<6;k++)fields[k].set(scratch[k]);
        pressure.fill(0);next.fill(0);
        for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){const i=y*w+x;div[i]=-(u[i+1]-u[i-1]+v[i+w]-v[i-w])*.5;}
        for(let iteration=0;iteration<12;iteration++){
          for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){const i=y*w+x;next[i]=(div[i]+pressure[i-1]+pressure[i+1]+pressure[i-w]+pressure[i+w])*.25;}
          pressure.set(next);
        }
        for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){const i=y*w+x;u[i]-=(pressure[i+1]-pressure[i-1])*.5;v[i]-=(pressure[i+w]-pressure[i-w])*.5;}
      }
      function state(time){const end=Math.max(0,Math.floor((time+(q.pre_roll??0))*30)),start=Math.max(...[...snapshots.keys()].filter(n=>n<=end));let fields=snapshots.get(start).map(a=>a.slice());
        for(let i=start;i<end;i++){advance(fields,i);if((i+1)%30===0&&!snapshots.has(i+1))snapshots.set(i+1,fields.map(a=>a.slice()));}return fields;
      }
      return {canvas,paint(time){const fields=state(time),cg=canvas.getContext('2d'),pixels=cg.createImageData(w,h),[u,v,d,r,g,b]=fields;
        for(let y=0;y<h;y++)for(let x=0;x<w;x++){const i=y*w+x,nx=x/w,ny=y/h;let alpha=1-Math.exp(-d[i]);
          pixels.data.set([r[i]/Math.max(d[i],1e-9)*255,g[i]/Math.max(d[i],1e-9)*255,b[i]/Math.max(d[i],1e-9)*255,alpha*255],i*4);
        }cg.putImageData(pixels,0,0);}};
    }
    return {reset(){caches.clear();},draw(g,b,p,s,t,layer){const q=layer.props;let cache=caches.get(q.emitters);if(!cache){cache=create(q,p,b);caches.set(q.emitters,cache);}cache.paint(t);g.save();
      if(q.mask==='circle'){g.beginPath();g.ellipse(0,0,b.w*.43,b.h*.43,0,0,Math.PI*2);g.clip();}
      if(q.mask==='mountains'){g.beginPath();g.moveTo(-b.w/2,b.h/2);for(let i=0;i<=200;i++){const x=i/200;g.lineTo((x-.5)*b.w,(.55-.17*Math.sin(x*8)-.12*Math.sin(x*17+.5)-.5)*b.h);}g.lineTo(b.w/2,b.h/2);g.closePath();g.clip();}
      g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';g.drawImage(cache.canvas,-b.w/2,-b.h/2,b.w,b.h);g.restore();}};
  };
})();
