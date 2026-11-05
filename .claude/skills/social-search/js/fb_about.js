(()=>{const imgs=[...document.querySelectorAll("svg image")].map(i=>i.getAttribute("xlink:href")||i.getAttribute("href")).filter(h=>h&&/t39\.30808-1\//.test(h)&&/mx(1080|2048)|s240|s320|s480/.test(h));
const m=document.querySelector("[role=main]");return JSON.stringify({pic:imgs.find(h=>/mx2048|s240|s320|s480/.test(h))||imgs[0]||"",t:(m?m.innerText:"").slice(0,3500)})})()
