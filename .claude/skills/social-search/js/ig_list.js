(async()=>{const W=ms=>new Promise(z=>setTimeout(z,ms));const dlg=document.querySelector('[role=dialog]');if(!dlg)return "NO DIALOG";
const box=[...dlg.querySelectorAll('div')].filter(e=>e.scrollHeight>e.clientHeight+20).sort((a,b)=>b.scrollHeight-a.scrollHeight)[0];
let last=-1,same=0;for(let i=0;i<50&&same<3;i++){box.scrollTop=box.scrollHeight;await W(5000+Math.random()*3000);const n=box.innerText.length;same=(n==last)?same+1:0;last=n;}
return box.innerText})()
