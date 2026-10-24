import"./CWj6FrbW.js";import"./69_IOA4Y.js";import{p as Be,g as Fe,m as L,o as Ve,i as o,h as d,z as je,n as le,q as Ne,u as Oe,c as h,r as w,v as Z,t as J,w as z,a as W,d as Ue,x as de,b as Ge,s as $e,y as fe,f as B,e as P,aY as He}from"./DajfU3-w.js";import{i as Xe}from"./DlpfjYNg.js";import{e as Ke,i as Ye}from"./AOCdcpaB.js";import{a as q,d as Ze,s as Je}from"./CVHVtH8W.js";import{b as Pe}from"./DXGK6XZS.js";import{i as Qe}from"./BWjieua0.js";import{p}from"./DqZP-Km8.js";import{t as I}from"./DLAhAT5M.js";import{c as et,s as tt}from"./Dgt2CsBR.js";import{d as ue,l as ot,z as rt}from"./BgLHvrt5.js";import{t as at}from"./s-8cNQne.js";import{X as it}from"./BrA8FMjg.js";var nt=B('<div class="flex items-center h-full"><div></div></div>'),st=B(`<div class=" text-gray-500 rounded-full cursor-not-allowed"><svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" fill="currentColor"><style>.spinner_OSmW {
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
							}</style><g class="spinner_OSmW"><rect x="11" y="1" width="2" height="5" opacity=".14"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(30 12 12)" opacity=".29"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(60 12 12)" opacity=".43"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(90 12 12)" opacity=".57"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(120 12 12)" opacity=".71"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(150 12 12)" opacity=".86"></rect><rect x="11" y="1" width="2" height="5" transform="rotate(180 12 12)"></rect></g></svg></div>`),ct=B('<button id="confirm-recording-button" type="button" class="p-1.5 bg-indigo-500 text-white dark:bg-indigo-500 dark:text-blue-950 rounded-full"><svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-4"><path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5"></path></svg></button>'),lt=B('<div><div class="flex items-center mr-1"><button type="button"><!></button></div> <div class="flex flex-1 self-center items-center justify-between ml-2 mx-1 overflow-hidden h-6" dir="rtl"><div class="flex items-center gap-0.5 h-6 w-full max-w-full overflow-hidden overflow-x-hidden flex-wrap"></div></div> <div class="flex"><div class="  mx-1.5 pr-1 flex justify-center items-center"><div> </div></div> <div class="flex items-center"><!></div></div></div>');function St(ge,g){Be(g,!1);const Q=()=>P(et,"$config",V),F=()=>P(tt,"$settings",V),_=()=>P(ve,"$i18n",V),[V,me]=$e();ue.extend(ot);const ve=Fe("i18n");let m=p(g,"recording",12,!1),ee=p(g,"transcribe",8,!0),we=p(g,"displayMedia",8,!1),he=p(g,"echoCancellation",8,!0),pe=p(g,"noiseSuppression",8,!0),ye=p(g,"autoGainControl",8,!0),be=p(g,"className",8," p-2.5 w-full max-w-full"),j=p(g,"onCancel",8,()=>{}),N=p(g,"onConfirm",8,e=>{}),l=L(!1),E=!1,T=L(0),O=null,D="";const ke=()=>{O=setInterval(()=>{He(T)},1e3)},xe=()=>{clearInterval(O),d(T,0)},_e=e=>{const t=Math.floor(e/60),r=e%60,i=r<10?`0${r}`:r;return`${t}:${i}`};let S=null;const te=async()=>{if("wakeLock"in navigator)try{S=await navigator.wakeLock.request("screen"),S.addEventListener("release",()=>{})}catch(e){}},U=async()=>{if(S){try{await S.release()}catch(e){}S=null}};let f,u,v,x=[];const Se=-45;let b=300,n=L(Array(b).fill(0));const Ce=e=>{let t=0;for(let r=0;r<e.length;r++){const i=(e[r]-128)/128;t+=i*i}return Math.sqrt(t/e.length)},Me=e=>{e=e*10;const r=Math.pow(e,1.5);return Math.min(1,Math.max(.01,r))},Re=e=>{const t=new AudioContext,r=t.createMediaStreamSource(e),i=t.createAnalyser();i.minDecibels=Se,r.connect(i);const a=i.frequencyBinCount,s=new Uint8Array(a),c=new Uint8Array(i.fftSize);(()=>{const y=()=>{if(!(!m()||o(l))){if(m()&&!o(l)){i.getByteTimeDomainData(c),i.getByteFrequencyData(s);const R=Ce(c);o(n).push(Me(R)),o(n).length>=b&&o(n).shift(),d(n,o(n))}window.requestAnimationFrame(y)}};window.requestAnimationFrame(y)})()},Le=async(e,t="wav")=>{var i,a,s,c,k,y;await fe();const r=rt(e,`Recording-${ue().format("L LT")}.${t}`);if(ee()){if(Q().audio.stt.engine==="web"||(((s=(a=(i=F())==null?void 0:i.audio)==null?void 0:a.stt)==null?void 0:s.engine)??"")==="web")return;const R=await at(localStorage.token,r,(y=(k=(c=F())==null?void 0:c.audio)==null?void 0:k.stt)==null?void 0:y.language).catch(Ie=>(I.error(`${Ie}`),null));R&&N()(R)}else N()({file:r,blob:e})},Ee=async()=>{var t,r,i;d(l,!0);try{if(we()){const a=await navigator.mediaDevices.getDisplayMedia({audio:!0});f=new MediaStream;for(const s of a.getAudioTracks())f.addTrack(s);for(const s of a.getVideoTracks())s.stop()}else f=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:he(),noiseSuppression:pe(),autoGainControl:ye()}})}catch(a){I.error(_().t("Error accessing media devices.")),d(l,!1),m(!1);return}const e=["audio/webm; codecs=opus","audio/webm","audio/ogg; codecs=opus","audio/mp4","audio/wav"];v=new MediaRecorder(f,{mimeType:e.find(a=>MediaRecorder.isTypeSupported(a))}),v.onstart=async()=>{d(l,!1),ke(),await te(),x=[],Re(f)},v.ondataavailable=a=>x.push(a.data),v.onstop=async()=>{var a;if(E){let s=((a=x[0])==null?void 0:a.type)||v.mimeType||"audio/webm",c=s.split("/")[1].split(";")[0]||"webm";s.startsWith("audio/")||(c="webm");const k=new Blob(x,{type:s});await Le(k,c),E=!1,d(l,!1)}x=[],m(!1)};try{v.start()}catch(a){I.error(_().t("Error starting recording.")),d(l,!1),m(!1);return}if(ee()&&(Q().audio.stt.engine==="web"||(((i=(r=(t=F())==null?void 0:t.audio)==null?void 0:r.stt)==null?void 0:i.engine)??"")==="web")&&("SpeechRecognition"in window||"webkitSpeechRecognition"in window)){D="",u=new(window.SpeechRecognition||window.webkitSpeechRecognition),u.continuous=!0;const a=2e3;let s;u.start(),u.onresult=async c=>{var y;clearTimeout(s);const k=c.results[Object.keys(c.results).length-1][0].transcript;D=`${D}${k}`,await fe(),(y=document.getElementById("chat-input"))==null||y.focus(),s=setTimeout(()=>{u.stop()},a)},u.onend=function(){re(),N()({text:D}),E=!1,d(l,!1)},u.onerror=function(c){I.error(_().t("Speech recognition error: {{error}}",{error:c.error})),j()(),G()}}},G=async()=>{u&&(u.onend=null),await oe()},oe=async()=>{m()&&v&&await v.stop(),u&&u.stop(),await U(),xe(),x=[],d(n,Array(b).fill(0)),f&&f.getTracks().forEach(t=>t.stop()),f=null},re=async()=>{d(l,!0),E=!0,m()&&v&&await v.stop(),clearInterval(O),await U(),f&&f.getTracks().forEach(t=>t.stop()),f=null};let $,H=L(),Te=L(300);const ae=e=>{e.key==="Escape"&&(e.preventDefault(),G(),j()())},ie=async()=>{m()&&document.visibilityState==="visible"&&await te()};Ve(()=>{window.addEventListener("keydown",ae),document.addEventListener("visibilitychange",ie),$=new ResizeObserver(()=>{b=Math.floor(window.innerWidth/4),o(n).length>b?d(n,o(n).slice(o(n).length-b)):d(n,Array(b-o(n).length).fill(0).concat(o(n)))}),$.observe(document.body)}),je(()=>{window.removeEventListener("keydown",ae),document.removeEventListener("visibilitychange",ie),U(),$.disconnect()}),le(()=>Ne(m()),()=>{m()?Ee():oe()}),le(()=>o(H),()=>{d(Te,Math.floor(o(H)/5))}),Oe(),Qe();var C=lt(),X=h(C),A=h(X),De=h(A);it(De,{className:"size-4"}),w(A),w(X);var M=Z(X,2),ne=h(M);Ke(ne,5,()=>(o(n),z(()=>o(n).slice().reverse())),Ye,(e,t)=>{var r=nt(),i=h(r);w(r),J(a=>{q(i,1,`w-[2px] shrink-0
                    
                    ${o(l)?" bg-gray-500 dark:bg-gray-400   ":"bg-indigo-500 dark:bg-indigo-400  "} 
                    
                    inline-block h-full`),Ze(i,`height: ${a??""}%;`)},[()=>(o(t),z(()=>Math.min(100,Math.max(14,o(t)*100))))]),W(e,r)}),w(ne),w(M);var se=Z(M,2),K=h(se),Y=h(K),Ae=h(Y,!0);w(Y),w(K);var ce=Z(K,2),ze=h(ce);{var We=e=>{var t=st();W(e,t)},qe=e=>{var t=ct();J(r=>Je(t,"aria-label",r),[()=>(_(),z(()=>_().t("Confirm recording")))]),de("click",t,async()=>{await re()}),W(e,t)};Xe(ze,e=>{o(l)?e(We):e(qe,-1)})}w(ce),w(se),w(C),J(e=>{q(C,1,`${o(l)?" bg-gray-100/50 dark:bg-gray-850/50":"bg-indigo-300/10 dark:bg-indigo-500/10 "} rounded-full flex justify-between ${be()??""}`,"svelte-nkn4fu"),q(A,1,`p-1.5

            ${o(l)?" bg-gray-200 dark:bg-gray-700/50":"bg-indigo-400/20 text-indigo-600 dark:text-indigo-300 "} 


             rounded-full`),M.dir=M.dir,q(Y,1,`text-sm
        
        
        ${o(l)?" text-gray-500  dark:text-gray-400  ":" text-indigo-400 "} 
       font-normal flex-1 mx-auto text-center`),Ue(Ae,e)},[()=>(o(T),z(()=>_e(o(T))))]),de("click",A,async()=>{G(),j()()}),Pe(C,"clientWidth",e=>d(H,e)),W(ge,C),Ge(),me()}export{St as V};
//# sourceMappingURL=CeasFhM0.js.map
