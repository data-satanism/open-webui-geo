import"./CWj6FrbW.js";import"./69_IOA4Y.js";import{p as Fe,g as Ve,m as L,d as je,h as o,e as d,l as Ne,n as le,q as Ue,u as Ge,c as k,r as y,z as Z,o as de,t as J,v as z,a as W,s as Oe,A as fe,b as $e,aE as ue,f as B,aN as Xe}from"./AZSZcOKz.js";import{i as He}from"./zDFWcGwk.js";import{e as Ke,i as Ze}from"./GEdOzpbO.js";import{a as q,b as Je,s as Pe}from"./JTxzyKAP.js";import{b as Qe}from"./CQX2wYt6.js";import{i as Ye}from"./BEOmFuJi.js";import{p as w}from"./CtP2XOWp.js";import{s as et,a as P}from"./BTAaVz5p.js";import{t as I}from"./ILG04y9v.js";import{j as ge,z as tt,c as ot,s as rt,X as at}from"./C6STRdfY.js";import{t as it}from"./CLrSvnyV.js";import{X as nt}from"./jB8XKHR2.js";var st=B('<div class="flex items-center h-full"><div></div></div>'),ct=B(`<div class=" text-gray-500 rounded-full cursor-not-allowed"><svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><style>.spinner_OSmW {
								transform-origin: center;
								animation: spinner_T6mA 0.75s step-end infinite;
							}
							@keyframes spinner_T6mA {
								8.3% {
									transform: rotate(30deg);
								}
								16.6% {
									transform: rotate(60deg);
								}
								25% {
									transform: rotate(90deg);
								}
								33.3% {
									transform: rotate(120deg);
								}
								41.6% {
									transform: rotate(150deg);
								}
								50% {
									transform: rotate(180deg);
								}
								58.3% {
									transform: rotate(210deg);
								}
								66.6% {
									transform: rotate(240deg);
								}
								75% {
									transform: rotate(270deg);
								}
								83.3% {
									transform: rotate(300deg);
								}
								91.6% {
									transform: rotate(330deg);
								}
								100% {
									transform: rotate(360deg);
								}
							}</style><g class="spinner_OSmW"><rect x="11" y="1" width="2" height="5" opacity=".14"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(30 12 12)" opacity=".29"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(60 12 12)" opacity=".43"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(90 12 12)" opacity=".57"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(120 12 12)" opacity=".71"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(150 12 12)" opacity=".86"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(180 12 12)"></rect></g></svg></div>`),lt=B('<button id="confirm-recording-button" type="button" class="p-1.5 bg-indigo-500 text-white dark:bg-indigo-500 dark:text-blue-950 rounded-full"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-4"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5"></path></svg></button>'),dt=B('<div><div class="flex items-center mr-1"><button type="button"><!></button></div> <div class="flex flex-1 self-center items-center justify-between ml-2 mx-1 overflow-hidden h-6" dir="rtl"><div class="flex items-center gap-0.5 h-6 w-full max-w-full overflow-hidden overflow-x-hidden flex-wrap"></div></div> <div class="flex"><div class="  mx-1.5 pr-1 flex justify-center items-center"><div> </div></div> <div class="flex items-center"><!></div></div></div>');function Ct(me,m){Fe(m,!1);const x=()=>P(we,"$i18n",V),Q=()=>P(ot,"$config",V),F=()=>P(rt,"$settings",V),[V,ve]=et();ge.extend(tt);const we=Ve("i18n");let u=w(m,"recording",12,!1),Y=w(m,"transcribe",8,!0),he=w(m,"displayMedia",8,!1),pe=w(m,"echoCancellation",8,!0),ye=w(m,"noiseSuppression",8,!0),be=w(m,"autoGainControl",8,!0),ke=w(m,"className",8," p-2.5 w-full max-w-full"),j=w(m,"onCancel",8,()=>{}),N=w(m,"onConfirm",8,e=>{}),l=L(!1),E=!1,T=L(0),U=null,A="";const xe=()=>{U=setInterval(()=>{Xe(T)},1e3)},_e=()=>{clearInterval(U),d(T,0)},Se=e=>{const t=Math.floor(e/60),r=e%60,i=r<10?`0${r}`:r;return`${t}:${i}`};let S=null;const ee=async()=>{if("wakeLock"in navigator)try{S=await navigator.wakeLock.request("screen"),S.addEventListener("release",()=>{})}catch(e){}},G=async()=>{if(S){try{await S.release()}catch(e){}S=null}};let g,f,v,_=[];const Ce=-45;let b=300,n=L(Array(b).fill(0));const Me=e=>{let t=0;for(let r=0;r<e.length;r++){const i=(e[r]-128)/128;t+=i*i}return Math.sqrt(t/e.length)},Re=e=>{e=e*10;const r=Math.pow(e,1.5);return Math.min(1,Math.max(.01,r))},Le=e=>{const t=new AudioContext,r=t.createMediaStreamSource(e),i=t.createAnalyser();i.minDecibels=Ce,r.connect(i);const a=i.frequencyBinCount,s=new Uint8Array(a),c=new Uint8Array(i.fftSize);(()=>{const p=()=>{if(!(!u()||o(l))){if(u()&&!o(l)){i.getByteTimeDomainData(c),i.getByteFrequencyData(s);const R=Me(c);o(n).push(Re(R)),o(n).length>=b&&o(n).shift(),d(n,o(n))}window.requestAnimationFrame(p)}};window.requestAnimationFrame(p)})()},Ee=async(e,t="wav")=>{var i,a,s,c,h,p;await ue();const r=at(e,`Recording-${ge().locale(x().language).format("L LT")}.${t}`);if(Y()){if(Q().audio.stt.engine==="web"||(((s=(a=(i=F())==null?void 0:i.audio)==null?void 0:a.stt)==null?void 0:s.engine)??"")==="web")return;const R=await it(localStorage.token,r,(p=(h=(c=F())==null?void 0:c.audio)==null?void 0:h.stt)==null?void 0:p.language).catch(Be=>(I.error(`${Be}`),null));R&&N()(R)}else N()({file:r,blob:e})},Te=async()=>{var t,r,i;d(l,!0);try{if(he()){const a=await navigator.mediaDevices.getDisplayMedia({audio:!0});g=new MediaStream;for(const s of a.getAudioTracks())g.addTrack(s);for(const s of a.getVideoTracks())s.stop()}else g=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:pe(),noiseSuppression:ye(),autoGainControl:be()}})}catch(a){I.error(x().t("Error accessing media devices.")),d(l,!1),u(!1);return}const e=["audio/webm; codecs=opus","audio/webm","audio/ogg; codecs=opus","audio/mp4","audio/wav"];v=new MediaRecorder(g,{mimeType:e.find(a=>MediaRecorder.isTypeSupported(a))}),v.onstart=async()=>{d(l,!1),xe(),await ee(),_=[],Le(g)},v.ondataavailable=a=>_.push(a.data),v.onstop=async()=>{var a;if(E){let s=((a=_[0])==null?void 0:a.type)||v.mimeType||"audio/webm",c=s.split("/")[1].split(";")[0]||"webm";s.startsWith("audio/")||(c="webm");const h=new Blob(_,{type:s});await Ee(h,c),E=!1,d(l,!1)}_=[],u(!1)};try{v.start()}catch(a){I.error(x().t("Error starting recording.")),d(l,!1),u(!1);return}if(Y()&&(Q().audio.stt.engine==="web"||(((i=(r=(t=F())==null?void 0:t.audio)==null?void 0:r.stt)==null?void 0:i.engine)??"")==="web")&&("SpeechRecognition"in window||"webkitSpeechRecognition"in window)){A="",f=new(window.SpeechRecognition||window.webkitSpeechRecognition),f.continuous=!0,f.interimResults=!0;const a=2e3;let s;f.start(),f.onresult=async c=>{var h;clearTimeout(s);for(const p of Array.from(c.results).slice(c.resultIndex))p.isFinal&&(A=`${A}${p[0].transcript}`);await ue(),(h=document.getElementById("chat-input"))==null||h.focus(),s=setTimeout(()=>{f.stop()},a)},f.onend=function(){oe(),N()({text:A}),E=!1,d(l,!1)},f.onerror=function(c){I.error(x().t("Speech recognition error: {{error}}",{error:c.error})),j()(),O()}}},O=async()=>{f&&(f.onend=null),await te()},te=async()=>{u()&&v&&await v.stop(),f&&f.stop(),await G(),_e(),_=[],d(n,Array(b).fill(0)),g&&g.getTracks().forEach(t=>t.stop()),g=null},oe=async()=>{d(l,!0),E=!0,u()&&v&&await v.stop(),clearInterval(U),await G(),g&&g.getTracks().forEach(t=>t.stop()),g=null};let $,X=L(),Ae=L(300);const re=e=>{u()&&e.key==="Escape"&&(e.preventDefault(),O(),j()())},ae=async()=>{u()&&document.visibilityState==="visible"&&await ee()};je(()=>{window.addEventListener("keydown",re),document.addEventListener("visibilitychange",ae),$=new ResizeObserver(()=>{b=Math.floor(window.innerWidth/4),o(n).length>b?d(n,o(n).slice(o(n).length-b)):d(n,Array(b-o(n).length).fill(0).concat(o(n)))}),$.observe(document.body)}),Ne(()=>{window.removeEventListener("keydown",re),document.removeEventListener("visibilitychange",ae),G(),$.disconnect()}),le(()=>Ue(u()),()=>{u()?Te():te()}),le(()=>o(X),()=>{d(Ae,Math.floor(o(X)/5))}),Ge(),Ye();var C=dt(),H=k(C),D=k(H),De=k(D);nt(De,{className:"size-4"}),y(D),y(H);var M=Z(H,2),ie=k(M);Ke(ie,5,()=>(o(n),z(()=>o(n).slice().reverse())),Ze,(e,t)=>{var r=st(),i=de(r);J(a=>{q(i,1,`w-[0.125rem] shrink-0
                    
                    ${o(l)?" bg-gray-500 dark:bg-gray-400   ":"bg-indigo-500 dark:bg-indigo-400  "} 
                    
                    inline-block h-full`),Je(i,`height: ${a??""}%;`)},[()=>(o(t),z(()=>Math.min(100,Math.max(14,o(t)*100))))]),W(e,r)}),y(ie),y(M);var ne=Z(M,2),K=k(ne),se=k(K),ze=de(se,!0);y(K);var ce=Z(K,2),We=k(ce);{var qe=e=>{var t=ct();W(e,t)},Ie=e=>{var t=lt();J(r=>Pe(t,"aria-label",r),[()=>(x(),z(()=>x().t("Confirm recording")))]),fe("click",t,async()=>{await oe()}),W(e,t)};He(We,e=>{o(l)?e(qe):e(Ie,-1)})}y(ce),y(ne),y(C),J(e=>{q(C,1,`${o(l)?" bg-gray-100/50 dark:bg-gray-850/50":"bg-indigo-300/10 dark:bg-indigo-500/10 "} rounded-full flex justify-between ${ke()??""}`,"svelte-nkn4fu"),q(D,1,`p-1.5

            ${o(l)?" bg-gray-200 dark:bg-gray-700/50":"bg-indigo-400/20 text-indigo-600 dark:text-indigo-300 "} 


             rounded-full`),M.dir=M.dir,q(se,1,`text-sm
        
        
        ${o(l)?" text-gray-500  dark:text-gray-400  ":" text-indigo-400 "} 
       font-normal flex-1 mx-auto text-center`),Oe(ze,e)},[()=>(o(T),z(()=>Se(o(T))))]),fe("click",D,async()=>{O(),j()()}),Qe(C,"clientWidth",e=>d(X,e)),W(me,C),$e(),ve()}export{Ct as V};
//# sourceMappingURL=_vKrNeIS.js.map
