import"./fjJtg2zo.js";import"./BoY66ijz.js";import{p as Ve,g as je,m as C,d as Ne,h as a,e as s,l as Ue,n as ue,q as Ge,u as Oe,c as y,r as w,y as Z,o as fe,t as $,v as M,a as T,s as He,z as me,b as Xe,C as K,f as I,ac as Ze}from"./Cu1SRIzq.js";import{i as $e}from"./lnCTSvpu.js";import{e as Ke,i as Je}from"./BM1P7zQw.js";import{a as A,b as Pe,s as J}from"./5ybce1gv.js";import{b as Qe}from"./BoHtGnqc.js";import{i as Ye}from"./CWLIPwYo.js";import{p as m}from"./8qJ-pp7W.js";import{a as P,s as et}from"./z6D3ChVu.js";import{t as D}from"./BW8yVPW8.js";import{n as ge,y as tt,c as ot,s as at,Z as rt}from"./BM0RHI8T.js";import{t as it}from"./C43wfgRO.js";import{X as nt}from"./GFj-yC6D.js";var st=I('<div class="flex items-center h-full"><div></div></div>'),ct=I(`<div class=" text-gray-500 rounded-full cursor-not-allowed"><svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><style>.spinner_OSmW {
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
							}</style><g class="spinner_OSmW"><rect x="11" y="1" width="2" height="5" opacity=".14"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(30 12 12)" opacity=".29"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(60 12 12)" opacity=".43"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(90 12 12)" opacity=".57"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(120 12 12)" opacity=".71"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(150 12 12)" opacity=".86"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(180 12 12)"></rect></g></svg></div>`),lt=I('<button type="button" class="p-1.5 bg-indigo-500 text-white dark:bg-indigo-500 dark:text-blue-950 rounded-full"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-4"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5"></path></svg></button>'),dt=I('<div><div class="flex items-center mr-1"><button type="button"><!></button></div> <div class="flex flex-1 self-center items-center justify-between ml-2 mx-1 overflow-hidden h-6" dir="rtl"><div class="flex items-center gap-0.5 h-6 w-full max-w-full overflow-hidden overflow-x-hidden flex-wrap"></div></div> <div class="flex"><div class="  mx-1.5 pr-1 flex justify-center items-center"><div> </div></div> <div class="flex items-center"><!></div></div></div>');function Mt(ve,l){Ve(l,!1);const g=()=>P(he,"$i18n",W),Q=()=>P(ot,"$config",W),B=()=>P(at,"$settings",W),[W,we]=et();ge.extend(tt);const he=je("i18n");let d=m(l,"recording",12,!1),Y=m(l,"transcribe",8,!0),ye=m(l,"displayMedia",8,!1),pe=m(l,"echoCancellation",8,!0),be=m(l,"noiseSuppression",8,!0),ke=m(l,"autoGainControl",8,!0),xe=m(l,"className",8," p-2.5 w-full max-w-full"),ee=m(l,"confirmButtonId",8,"confirm-recording-button"),q=m(l,"onCancel",8,()=>{}),z=m(l,"onConfirm",8,t=>{}),n=C(!1),R=!1,E=C(0),F=null,L="";const _e=()=>{F=setInterval(()=>{Ze(E)},1e3)},Se=()=>{clearInterval(F),s(E,0)},Ce=t=>{const e=Math.floor(t/60),o=t%60,r=o<10?`0${o}`:o;return`${e}:${r}`};let b=null;const te=async()=>{if("wakeLock"in navigator)try{b=await navigator.wakeLock.request("screen"),b.addEventListener("release",()=>{})}catch(t){}},V=async()=>{if(b){try{await b.release()}catch(t){}b=null}};let u,k=null,c,f,p=[];const Me=-45;let h=300,i=C(Array(h).fill(0));const Re=t=>{let e=0;for(let o=0;o<t.length;o++){const r=(t[o]-128)/128;e+=r*r}return Math.sqrt(e/t.length)},Ee=t=>{t=t*10;const o=Math.pow(t,1.5);return Math.min(1,Math.max(.01,o))},j=()=>{k?.close(),k=null},Le=t=>{k=new AudioContext;const e=k.createMediaStreamSource(t),o=k.createAnalyser();o.minDecibels=Me,e.connect(o);const r=o.frequencyBinCount,v=new Uint8Array(r),le=new Uint8Array(o.fftSize);(()=>{const de=()=>{if(!(!d()||a(n))){if(d()&&!a(n)){o.getByteTimeDomainData(le),o.getByteFrequencyData(v);const Fe=Re(le);a(i).push(Ee(Fe)),a(i).length>=h&&a(i).shift(),s(i,a(i))}window.requestAnimationFrame(de)}};window.requestAnimationFrame(de)})()},Te=async(t,e="wav")=>{await K();const o=rt(t,`Recording-${ge().locale(g().language).format("L LT")}.${e}`);if(Y()){if(Q().audio.stt.engine==="web"||(B()?.audio?.stt?.engine??"")==="web")return;const r=await it(localStorage.token,o,B()?.audio?.stt?.language).catch(v=>(D.error(`${v}`),null));r&&z()(r)}else z()({file:o,blob:t})},Ae=async()=>{s(n,!0);try{if(ye()){const e=await navigator.mediaDevices.getDisplayMedia({audio:!0});u=new MediaStream;for(const o of e.getAudioTracks())u.addTrack(o);for(const o of e.getVideoTracks())o.stop()}else u=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:pe(),noiseSuppression:be(),autoGainControl:ke()}})}catch(e){D.error(g().t("Error accessing media devices.")),s(n,!1),d(!1);return}const t=["audio/webm; codecs=opus","audio/webm","audio/ogg; codecs=opus","audio/mp4","audio/wav"];f=new MediaRecorder(u,{mimeType:t.find(e=>MediaRecorder.isTypeSupported(e))}),f.onstart=async()=>{s(n,!1),_e(),(document.activeElement===document.body||!document.activeElement?.checkVisibility())&&(await K(),document.getElementById(ee())?.focus()),await te(),p=[],Le(u)},f.ondataavailable=e=>p.push(e.data),f.onstop=async()=>{if(R){let e=p[0]?.type||f.mimeType||"audio/webm",o=e.split("/")[1].split(";")[0]||"webm";e.startsWith("audio/")||(o="webm");const r=new Blob(p,{type:e});await Te(r,o),R=!1,s(n,!1)}p=[],d(!1)};try{f.start()}catch(e){D.error(g().t("Error starting recording.")),s(n,!1),d(!1);return}if(Y()&&(Q().audio.stt.engine==="web"||(B()?.audio?.stt?.engine??"")==="web")&&("SpeechRecognition"in window||"webkitSpeechRecognition"in window)){L="",c=new(window.SpeechRecognition||window.webkitSpeechRecognition),c.continuous=!0,c.interimResults=!0;const e=2e3;let o;c.start(),c.onresult=async r=>{clearTimeout(o);for(const v of Array.from(r.results).slice(r.resultIndex))v.isFinal&&(L=`${L}${v[0].transcript}`);await K(),document.getElementById("chat-input")?.focus(),o=setTimeout(()=>{c.stop()},e)},c.onend=function(){oe(),z()({text:L}),R=!1,s(n,!1)},c.onerror=function(r){D.error(g().t("Speech recognition error: {{error}}",{error:r.error})),q()(),N()}}},N=async()=>{c&&(c.onend=null),await U()},U=async()=>{d()&&f&&await f.stop(),c&&c.stop(),await V(),Se(),p=[],s(i,Array(h).fill(0)),u&&u.getTracks().forEach(e=>e.stop()),u=null,j()},oe=async()=>{s(n,!0),R=!0,d()&&f&&await f.stop(),clearInterval(F),await V(),u&&u.getTracks().forEach(e=>e.stop()),u=null,j()};let G,O=C(),De=C(300);const ae=t=>{d()&&t.key==="Escape"&&(t.preventDefault(),N(),q()())},re=async()=>{d()&&document.visibilityState==="visible"&&await te()};Ne(()=>{window.addEventListener("keydown",ae),document.addEventListener("visibilitychange",re),G=new ResizeObserver(()=>{h=Math.floor(window.innerWidth/4),a(i).length>h?s(i,a(i).slice(a(i).length-h)):s(i,Array(h-a(i).length).fill(0).concat(a(i)))}),G.observe(document.body)}),Ue(()=>{window.removeEventListener("keydown",ae),document.removeEventListener("visibilitychange",re),U(),V(),j(),G.disconnect()}),ue(()=>Ge(d()),()=>{d()?Ae():U()}),ue(()=>a(O),()=>{s(De,Math.floor(a(O)/5))}),Oe(),Ye();var x=dt(),H=y(x),_=y(H),Ie=y(_);nt(Ie,{className:"size-4"}),w(_),w(H);var S=Z(H,2),ie=y(S);Ke(ie,5,()=>(a(i),M(()=>a(i).slice().reverse())),Je,(t,e)=>{var o=st(),r=fe(o);$(v=>{A(r,1,`w-[0.125rem] shrink-0
                    
                    ${a(n)?" bg-gray-500 dark:bg-gray-400   ":"bg-indigo-500 dark:bg-indigo-400  "} 
                    
                    inline-block h-full`),Pe(r,`height: ${v??""}%;`)},[()=>(a(e),M(()=>Math.min(100,Math.max(14,a(e)*100))))]),T(t,o)}),w(ie),w(S);var ne=Z(S,2),X=y(ne),se=y(X),Be=fe(se,!0);w(X);var ce=Z(X,2),We=y(ce);{var qe=t=>{var e=ct();T(t,e)},ze=t=>{var e=lt();$(o=>{J(e,"id",ee()),J(e,"aria-label",o)},[()=>(g(),M(()=>g().t("Confirm recording")))]),me("click",e,async()=>{await oe()}),T(t,e)};$e(We,t=>{a(n)?t(qe):t(ze,-1)})}w(ce),w(ne),w(x),$((t,e)=>{A(x,1,`${a(n)?" bg-gray-100/50 dark:bg-gray-850/50":"bg-indigo-300/10 dark:bg-indigo-500/10 "} rounded-full flex justify-between ${xe()??""}`,"svelte-nkn4fu"),A(_,1,`p-1.5

            ${a(n)?" bg-gray-200 dark:bg-gray-700/50":"bg-indigo-400/20 text-indigo-600 dark:text-indigo-300 "} 


             rounded-full`),J(_,"aria-label",t),S.dir=S.dir,A(se,1,`text-sm
        
        
        ${a(n)?" text-gray-500  dark:text-gray-400  ":" text-indigo-400 "} 
       font-normal flex-1 mx-auto text-center`),He(Be,e)},[()=>(g(),M(()=>g().t("Cancel"))),()=>(a(E),M(()=>Ce(a(E))))]),me("click",_,async()=>{N(),q()()}),Qe(x,"clientWidth",t=>s(O,t)),T(ve,x),Xe(),we()}export{Mt as V};
//# sourceMappingURL=CaxgQtxp.js.map
