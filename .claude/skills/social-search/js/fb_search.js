(async()=>{const W=ms=>new Promise(z=>setTimeout(z,ms));for(let i=0;i<3;i++){scrollBy(0,3000);await W(2500)}
const seen=new Set(),out=[];for(const a of document.querySelectorAll('[role=feed] a[href*="facebook.com/"]')){
 const t=a.innerText.trim(); if(!t||seen.has(a.href.split('?')[0]+t)) continue;
 let box=a; for(let i=0;i<8&&box&&!box.querySelector('image,img');i++) box=box.parentElement;
 if(!box) continue; let card=box; for(let i=0;i<4;i++) card=card.parentElement;
 const img=box.querySelector('image')?.getAttribute('xlink:href')||box.querySelector('img')?.src||'';
 seen.add(a.href.split('?')[0]+t); out.push([t,a.href.replace(/[?&]__.*$/,''),card.innerText.replace(/\n+/g,' | ').slice(0,200),img].join('\t'));}
return out.join('\n')})()
