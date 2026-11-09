import{M as Di,H as ki,V as v,Q as A,aB as Gt,y as V,G as Xe,am as rn,a5 as on,k as sn,g as Rt,i as Yt,aC as Fi,aD as Hi,aE as Wi,aF as zi,aG as Ke,aH as de,C as ne,ab as he,O as at,c as X,aI as ji,B as ve,ap as qi,ao as Xi,aJ as an,as as Qt,aK as Gi,aL as vt,m as qe,I as $n,e as Zn,ay as Yi,az as Ft,a4 as Jn,at as Kn,z as Qi,a0 as $i,a1 as Zi,W as Ji,S as Ki,Z as er,X as tr,a2 as nr,aM as ln,ax as un,aN as ir}from"./DXDqiNAX.js";import{GLTFLoader as ei}from"./D-5ny4kB.js";import{v as rr}from"./BfDxyTPZ.js";/*!
 * @pixiv/three-vrm v3.5.5
 * VRM file loader for three.js.
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 */var ct=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())}),I=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())}),dn=class extends at{constructor(e){super(),this.weight=0,this.isBinary=!1,this.overrideBlink="none",this.overrideLookAt="none",this.overrideMouth="none",this._binds=[],this.name=`VRMExpression_${e}`,this.expressionName=e,this.type="VRMExpression",this.visible=!1}get binds(){return this._binds}get overrideBlinkAmount(){return this.overrideBlink==="block"?0<this.outputWeight?1:0:this.overrideBlink==="blend"?this.outputWeight:0}get overrideLookAtAmount(){return this.overrideLookAt==="block"?0<this.outputWeight?1:0:this.overrideLookAt==="blend"?this.outputWeight:0}get overrideMouthAmount(){return this.overrideMouth==="block"?0<this.outputWeight?1:0:this.overrideMouth==="blend"?this.outputWeight:0}get outputWeight(){return this.isBinary?this.weight>.5?1:0:this.weight}addBind(e){this._binds.push(e)}deleteBind(e){const t=this._binds.indexOf(e);t>=0&&this._binds.splice(t,1)}applyWeight(e){var t;let n=this.outputWeight;n*=(t=e?.multiplier)!=null?t:1,this.isBinary&&n<1&&(n=0),this._binds.forEach(i=>i.applyWeight(n))}clearAppliedWeight(){this._binds.forEach(e=>e.clearAppliedWeight())}};function ti(e,t,n){var i,r;const o=e.parser.json,s=(i=o.nodes)==null?void 0:i[t];if(s==null)return console.warn(`extractPrimitivesInternal: Attempt to use nodes[${t}] of glTF but the node doesn't exist`),null;const l=s.mesh;if(l==null)return null;const a=(r=o.meshes)==null?void 0:r[l];if(a==null)return console.warn(`extractPrimitivesInternal: Attempt to use meshes[${l}] of glTF but the mesh doesn't exist`),null;const u=a.primitives.length,d=[];return n.traverse(c=>{d.length<u&&c.isMesh&&d.push(c)}),d}function cn(e,t){return I(this,null,function*(){const n=yield e.parser.getDependency("node",t);return ti(e,t,n)})}function hn(e){return I(this,null,function*(){const t=yield e.parser.getDependencies("node"),n=new Map;return t.forEach((i,r)=>{const o=ti(e,r,i);o!=null&&n.set(r,o)}),n})}var Ht={Aa:"aa",Ih:"ih",Ou:"ou",Ee:"ee",Oh:"oh",Blink:"blink",Happy:"happy",Angry:"angry",Sad:"sad",Relaxed:"relaxed",LookUp:"lookUp",Surprised:"surprised",LookDown:"lookDown",LookLeft:"lookLeft",LookRight:"lookRight",BlinkLeft:"blinkLeft",BlinkRight:"blinkRight",Neutral:"neutral"};function ni(e){return Math.max(Math.min(e,1),0)}var pn=class ii{constructor(){this.blinkExpressionNames=["blink","blinkLeft","blinkRight"],this.lookAtExpressionNames=["lookLeft","lookRight","lookUp","lookDown"],this.mouthExpressionNames=["aa","ee","ih","oh","ou"],this._expressions=[],this._expressionMap={}}get expressions(){return this._expressions.concat()}get expressionMap(){return Object.assign({},this._expressionMap)}get presetExpressionMap(){const t={},n=new Set(Object.values(Ht));return Object.entries(this._expressionMap).forEach(([i,r])=>{n.has(i)&&(t[i]=r)}),t}get customExpressionMap(){const t={},n=new Set(Object.values(Ht));return Object.entries(this._expressionMap).forEach(([i,r])=>{n.has(i)||(t[i]=r)}),t}copy(t){return this._expressions.concat().forEach(i=>{this.unregisterExpression(i)}),t._expressions.forEach(i=>{this.registerExpression(i)}),this.blinkExpressionNames=t.blinkExpressionNames.concat(),this.lookAtExpressionNames=t.lookAtExpressionNames.concat(),this.mouthExpressionNames=t.mouthExpressionNames.concat(),this}clone(){return new ii().copy(this)}getExpression(t){var n;return(n=this._expressionMap[t])!=null?n:null}registerExpression(t){this._expressions.push(t),this._expressionMap[t.expressionName]=t}unregisterExpression(t){const n=this._expressions.indexOf(t);n===-1&&console.warn("VRMExpressionManager: The specified expressions is not registered"),this._expressions.splice(n,1),delete this._expressionMap[t.expressionName]}getValue(t){var n;const i=this.getExpression(t);return(n=i?.weight)!=null?n:null}setValue(t,n){const i=this.getExpression(t);i&&(i.weight=ni(n))}resetValues(){this._expressions.forEach(t=>{t.weight=0})}getExpressionTrackName(t){const n=this.getExpression(t);return n?`${n.name}.weight`:null}update(){const t=this._calculateWeightMultipliers();this._expressions.forEach(n=>{n.clearAppliedWeight()}),this._expressions.forEach(n=>{let i=1;const r=n.expressionName;this.blinkExpressionNames.indexOf(r)!==-1&&(i*=t.blink),this.lookAtExpressionNames.indexOf(r)!==-1&&(i*=t.lookAt),this.mouthExpressionNames.indexOf(r)!==-1&&(i*=t.mouth),n.applyWeight({multiplier:i})})}_calculateWeightMultipliers(){let t=1,n=1,i=1;return this._expressions.forEach(r=>{t-=r.overrideBlinkAmount,n-=r.overrideLookAtAmount,i-=r.overrideMouthAmount}),t=Math.max(0,t),n=Math.max(0,n),i=Math.max(0,i),{blink:t,lookAt:n,mouth:i}}},et={Color:"color",EmissionColor:"emissionColor",ShadeColor:"shadeColor",RimColor:"rimColor",OutlineColor:"outlineColor"},or={_Color:et.Color,_EmissionColor:et.EmissionColor,_ShadeColor:et.ShadeColor,_RimColor:et.RimColor,_OutlineColor:et.OutlineColor},sr=new ne,ri=class oi{constructor({material:t,type:n,targetValue:i,targetAlpha:r}){this.material=t,this.type=n,this.targetValue=i,this.targetAlpha=r??1;const o=this._initColorBindState(),s=this._initAlphaBindState();this._state={color:o,alpha:s}}applyWeight(t){const{color:n,alpha:i}=this._state;if(n!=null){const{propertyName:r,deltaValue:o}=n,s=this.material[r];s?.add(sr.copy(o).multiplyScalar(t))}if(i!=null){const{propertyName:r,deltaValue:o}=i;this.material[r]!=null&&(this.material[r]+=o*t)}}clearAppliedWeight(){const{color:t,alpha:n}=this._state;if(t!=null){const{propertyName:i,initialValue:r}=t,o=this.material[i];o?.copy(r)}if(n!=null){const{propertyName:i,initialValue:r}=n;this.material[i]!=null&&(this.material[i]=r)}}_initColorBindState(){var t,n,i;const{material:r,type:o,targetValue:s}=this,l=this._getPropertyNameMap(),a=(n=(t=l?.[o])==null?void 0:t[0])!=null?n:null;if(a==null)return console.warn(`Tried to add a material color bind to the material ${(i=r.name)!=null?i:"(no name)"}, the type ${o} but the material or the type is not supported.`),null;const d=r[a].clone(),c=new ne(s.r-d.r,s.g-d.g,s.b-d.b);return{propertyName:a,initialValue:d,deltaValue:c}}_initAlphaBindState(){var t,n,i;const{material:r,type:o,targetAlpha:s}=this,l=this._getPropertyNameMap(),a=(n=(t=l?.[o])==null?void 0:t[1])!=null?n:null;if(a==null&&s!==1)return console.warn(`Tried to add a material alpha bind to the material ${(i=r.name)!=null?i:"(no name)"}, the type ${o} but the material or the type does not support alpha.`),null;if(a==null)return null;const u=r[a],d=s-u;return{propertyName:a,initialValue:u,deltaValue:d}}_getPropertyNameMap(){var t,n;return(n=(t=Object.entries(oi._propertyNameMapMap).find(([i])=>this.material[i]===!0))==null?void 0:t[1])!=null?n:null}};ri._propertyNameMapMap={isMeshStandardMaterial:{color:["color","opacity"],emissionColor:["emissive",null]},isMeshBasicMaterial:{color:["color","opacity"]},isMToonMaterial:{color:["color","opacity"],emissionColor:["emissive",null],outlineColor:["outlineColorFactor",null],matcapColor:["matcapFactor",null],rimColor:["parametricRimColorFactor",null],shadeColor:["shadeColorFactor",null]}};var fn=ri,Mt=class{constructor({primitives:e,index:t,weight:n}){this.primitives=e,this.index=t,this.weight=n}applyWeight(e){this.primitives.forEach(t=>{var n;((n=t.morphTargetInfluences)==null?void 0:n[this.index])!=null&&(t.morphTargetInfluences[this.index]+=this.weight*e)})}clearAppliedWeight(){this.primitives.forEach(e=>{var t;((t=e.morphTargetInfluences)==null?void 0:t[this.index])!=null&&(e.morphTargetInfluences[this.index]=0)})}},mn=new qe,si=class ai{constructor({material:t,scale:n,offset:i}){var r,o;this.material=t,this.scale=n,this.offset=i;const s=(r=Object.entries(ai._propertyNamesMap).find(([l])=>t[l]===!0))==null?void 0:r[1];s==null?(console.warn(`Tried to add a texture transform bind to the material ${(o=t.name)!=null?o:"(no name)"} but the material is not supported.`),this._properties=[]):(this._properties=[],s.forEach(l=>{var a;const u=(a=t[l])==null?void 0:a.clone();if(!u)return null;t[l]=u;const d=u.offset.clone(),c=u.repeat.clone(),h=i.clone().sub(d),p=n.clone().sub(c);this._properties.push({name:l,initialOffset:d,deltaOffset:h,initialScale:c,deltaScale:p})}))}applyWeight(t){this._properties.forEach(n=>{const i=this.material[n.name];i!==void 0&&(i.offset.add(mn.copy(n.deltaOffset).multiplyScalar(t)),i.repeat.add(mn.copy(n.deltaScale).multiplyScalar(t)))})}clearAppliedWeight(){this._properties.forEach(t=>{const n=this.material[t.name];n!==void 0&&(n.offset.copy(t.initialOffset),n.repeat.copy(t.initialScale))})}};si._propertyNamesMap={isMeshStandardMaterial:["map","emissiveMap","bumpMap","normalMap","displacementMap","roughnessMap","metalnessMap","alphaMap"],isMeshBasicMaterial:["map","specularMap","alphaMap"],isMToonMaterial:["map","normalMap","emissiveMap","shadeMultiplyTexture","rimMultiplyTexture","outlineWidthMultiplyTexture","uvAnimationMaskTexture"]};var gn=si,ar=new Set(["1.0","1.0-beta"]),li=class ui{get name(){return"VRMExpressionLoaderPlugin"}constructor(t){this.parser=t}afterRoot(t){return I(this,null,function*(){t.userData.vrmExpressionManager=yield this._import(t)})}_import(t){return I(this,null,function*(){const n=yield this._v1Import(t);if(n)return n;const i=yield this._v0Import(t);return i||null})}_v1Import(t){return I(this,null,function*(){var n,i;const r=this.parser.json;if(!(((n=r.extensionsUsed)==null?void 0:n.indexOf("VRMC_vrm"))!==-1))return null;const s=(i=r.extensions)==null?void 0:i.VRMC_vrm;if(!s)return null;const l=s.specVersion;if(!ar.has(l))return console.warn(`VRMExpressionLoaderPlugin: Unknown VRMC_vrm specVersion "${l}"`),null;const a=s.expressions;if(!a)return null;const u=new Set(Object.values(Ht)),d=new Map;a.preset!=null&&Object.entries(a.preset).forEach(([h,p])=>{if(p!=null){if(!u.has(h)){console.warn(`VRMExpressionLoaderPlugin: Unknown preset name "${h}" detected. Ignoring the expression`);return}d.set(h,p)}}),a.custom!=null&&Object.entries(a.custom).forEach(([h,p])=>{if(u.has(h)){console.warn(`VRMExpressionLoaderPlugin: Custom expression cannot have preset name "${h}". Ignoring the expression`);return}d.set(h,p)});const c=new pn;return yield Promise.all(Array.from(d.entries()).map(h=>I(this,[h],function*([p,f]){var m,_,g,M,y,x,R;const T=new dn(p);if(t.scene.add(T),T.isBinary=(m=f.isBinary)!=null?m:!1,T.overrideBlink=(_=f.overrideBlink)!=null?_:"none",T.overrideLookAt=(g=f.overrideLookAt)!=null?g:"none",T.overrideMouth=(M=f.overrideMouth)!=null?M:"none",(y=f.morphTargetBinds)==null||y.forEach(S=>I(this,null,function*(){var P;if(S.node===void 0||S.index===void 0)return;const U=yield cn(t,S.node),L=S.index;if(!U.every(N=>Array.isArray(N.morphTargetInfluences)&&L<N.morphTargetInfluences.length)){console.warn(`VRMExpressionLoaderPlugin: ${f.name} attempts to index morph #${L} but not found.`);return}T.addBind(new Mt({primitives:U,index:L,weight:(P=S.weight)!=null?P:1}))})),f.materialColorBinds||f.textureTransformBinds){const S=[];t.scene.traverse(P=>{const U=P.material;U&&(Array.isArray(U)?S.push(...U):S.push(U))}),(x=f.materialColorBinds)==null||x.forEach(P=>I(this,null,function*(){S.filter(L=>{var N;const F=(N=this.parser.associations.get(L))==null?void 0:N.materials;return P.material===F}).forEach(L=>{T.addBind(new fn({material:L,type:P.type,targetValue:new ne().fromArray(P.targetValue),targetAlpha:P.targetValue[3]}))})})),(R=f.textureTransformBinds)==null||R.forEach(P=>I(this,null,function*(){S.filter(L=>{var N;const F=(N=this.parser.associations.get(L))==null?void 0:N.materials;return P.material===F}).forEach(L=>{var N,F;T.addBind(new gn({material:L,offset:new qe().fromArray((N=P.offset)!=null?N:[0,0]),scale:new qe().fromArray((F=P.scale)!=null?F:[1,1])}))})}))}c.registerExpression(T)}))),c})}_v0Import(t){return I(this,null,function*(){var n;const i=this.parser.json,r=(n=i.extensions)==null?void 0:n.VRM;if(!r)return null;const o=r.blendShapeMaster;if(!o)return null;const s=new pn,l=o.blendShapeGroups;if(!l)return s;const a=new Set;return yield Promise.all(l.map(u=>I(this,null,function*(){var d;const c=u.presetName,h=c!=null&&ui.v0v1PresetNameMap[c]||null,p=h??u.name;if(p==null){console.warn("VRMExpressionLoaderPlugin: One of custom expressions has no name. Ignoring the expression");return}if(a.has(p)){console.warn(`VRMExpressionLoaderPlugin: An expression preset ${c} has duplicated entries. Ignoring the expression`);return}a.add(p);const f=new dn(p);t.scene.add(f),f.isBinary=(d=u.isBinary)!=null?d:!1,u.binds&&u.binds.forEach(_=>I(this,null,function*(){var g;if(_.mesh===void 0||_.index===void 0)return;const M=[];if((g=i.nodes)==null||g.forEach((x,R)=>{x.mesh===_.mesh&&M.push(R)}),M.length===0){console.warn(`VRMExpressionLoaderPlugin: ${u.name} attempts to bind a morph target to the mesh #${_.mesh} but the mesh is not found or not used in the scene. Ignoring the bind.`);return}const y=_.index;yield Promise.all(M.map(x=>I(this,null,function*(){var R;const T=yield cn(t,x);if(!T.every(S=>Array.isArray(S.morphTargetInfluences)&&y<S.morphTargetInfluences.length)){console.warn(`VRMExpressionLoaderPlugin: ${u.name} attempts to index ${y}th morph but not found.`);return}f.addBind(new Mt({primitives:T,index:y,weight:.01*((R=_.weight)!=null?R:100)}))})))}));const m=u.materialValues;m&&m.length!==0&&m.forEach(_=>{if(_.materialName===void 0||_.propertyName===void 0||_.targetValue===void 0)return;const g=[];t.scene.traverse(y=>{if(y.material){const x=y.material;Array.isArray(x)?g.push(...x.filter(R=>(R.name===_.materialName||R.name===_.materialName+" (Outline)")&&g.indexOf(R)===-1)):x.name===_.materialName&&g.indexOf(x)===-1&&g.push(x)}});const M=_.propertyName;g.forEach(y=>{if(M==="_MainTex_ST"){const R=new qe(_.targetValue[0],_.targetValue[1]),T=new qe(_.targetValue[2],_.targetValue[3]);T.y=1-T.y-R.y,f.addBind(new gn({material:y,scale:R,offset:T}));return}const x=or[M];if(x){f.addBind(new fn({material:y,type:x,targetValue:new ne().fromArray(_.targetValue),targetAlpha:_.targetValue[3]}));return}console.warn(M+" is not supported")})}),s.registerExpression(f)}))),s})}};li.v0v1PresetNameMap={a:"aa",e:"ee",i:"ih",o:"oh",u:"ou",blink:"blink",joy:"happy",angry:"angry",sorrow:"sad",fun:"relaxed",lookup:"lookUp",lookdown:"lookDown",lookleft:"lookLeft",lookright:"lookRight",blink_l:"blinkLeft",blink_r:"blinkRight",neutral:"neutral"};var lr=li,$t=class ze{constructor(t,n){this._firstPersonOnlyLayer=ze.DEFAULT_FIRSTPERSON_ONLY_LAYER,this._thirdPersonOnlyLayer=ze.DEFAULT_THIRDPERSON_ONLY_LAYER,this._initializedLayers=!1,this.humanoid=t,this.meshAnnotations=n}copy(t){if(this.humanoid!==t.humanoid)throw new Error("VRMFirstPerson: humanoid must be same in order to copy");return this.meshAnnotations=t.meshAnnotations.map(n=>({meshes:n.meshes.concat(),type:n.type})),this}clone(){return new ze(this.humanoid,this.meshAnnotations).copy(this)}get firstPersonOnlyLayer(){return this._firstPersonOnlyLayer}get thirdPersonOnlyLayer(){return this._thirdPersonOnlyLayer}setup({firstPersonOnlyLayer:t=ze.DEFAULT_FIRSTPERSON_ONLY_LAYER,thirdPersonOnlyLayer:n=ze.DEFAULT_THIRDPERSON_ONLY_LAYER}={}){this._initializedLayers||(this._firstPersonOnlyLayer=t,this._thirdPersonOnlyLayer=n,this.meshAnnotations.forEach(i=>{i.meshes.forEach(r=>{i.type==="firstPersonOnly"?(r.layers.set(this._firstPersonOnlyLayer),r.traverse(o=>o.layers.set(this._firstPersonOnlyLayer))):i.type==="thirdPersonOnly"?(r.layers.set(this._thirdPersonOnlyLayer),r.traverse(o=>o.layers.set(this._thirdPersonOnlyLayer))):i.type==="auto"&&this._createHeadlessModel(r)})}),this._initializedLayers=!0)}_excludeTriangles(t,n,i,r){let o=0;if(n!=null&&n.length>0)for(let s=0;s<t.length;s+=3){const l=t[s],a=t[s+1],u=t[s+2],d=n[l],c=i[l];if(d[0]>0&&r.includes(c[0])||d[1]>0&&r.includes(c[1])||d[2]>0&&r.includes(c[2])||d[3]>0&&r.includes(c[3]))continue;const h=n[a],p=i[a];if(h[0]>0&&r.includes(p[0])||h[1]>0&&r.includes(p[1])||h[2]>0&&r.includes(p[2])||h[3]>0&&r.includes(p[3]))continue;const f=n[u],m=i[u];f[0]>0&&r.includes(m[0])||f[1]>0&&r.includes(m[1])||f[2]>0&&r.includes(m[2])||f[3]>0&&r.includes(m[3])||(t[o++]=l,t[o++]=a,t[o++]=u)}return o}_createErasedMesh(t,n){const i=new Xi(t.geometry.clone(),t.material);i.name=`${t.name}(erase)`,i.frustumCulled=t.frustumCulled,i.layers.set(this._firstPersonOnlyLayer);const r=i.geometry,o=r.getAttribute("skinIndex"),s=o instanceof an?[]:o.array,l=[];for(let m=0;m<s.length;m+=4)l.push([s[m],s[m+1],s[m+2],s[m+3]]);const a=r.getAttribute("skinWeight"),u=a instanceof an?[]:a.array,d=[];for(let m=0;m<u.length;m+=4)d.push([u[m],u[m+1],u[m+2],u[m+3]]);const c=r.getIndex();if(!c)throw new Error("The geometry doesn't have an index buffer");const h=Array.from(c.array),p=this._excludeTriangles(h,d,l,n),f=[];for(let m=0;m<p;m++)f[m]=h[m];return r.setIndex(f),t.onBeforeRender&&(i.onBeforeRender=t.onBeforeRender),i.bind(new Qt(t.skeleton.bones,t.skeleton.boneInverses),new he),i}_createHeadlessModelForSkinnedMesh(t,n){const i=[];if(n.skeleton.bones.forEach((o,s)=>{this._isEraseTarget(o)&&i.push(s)}),!i.length){n.layers.enable(this._thirdPersonOnlyLayer),n.layers.enable(this._firstPersonOnlyLayer);return}n.layers.set(this._thirdPersonOnlyLayer);const r=this._createErasedMesh(n,i);t.add(r)}_createHeadlessModel(t){if(t.type==="Group")if(t.layers.set(this._thirdPersonOnlyLayer),this._isEraseTarget(t))t.traverse(n=>n.layers.set(this._thirdPersonOnlyLayer));else{const n=new Xe;n.name=`_headless_${t.name}`,n.layers.set(this._firstPersonOnlyLayer),t.parent.add(n),t.children.filter(i=>i.type==="SkinnedMesh").forEach(i=>{const r=i;this._createHeadlessModelForSkinnedMesh(n,r)})}else if(t.type==="SkinnedMesh"){const n=t;this._createHeadlessModelForSkinnedMesh(t.parent,n)}else this._isEraseTarget(t)&&(t.layers.set(this._thirdPersonOnlyLayer),t.traverse(n=>n.layers.set(this._thirdPersonOnlyLayer)))}_isEraseTarget(t){return t===this.humanoid.getRawBoneNode("head")?!0:t.parent?this._isEraseTarget(t.parent):!1}};$t.DEFAULT_FIRSTPERSON_ONLY_LAYER=9;$t.DEFAULT_THIRDPERSON_ONLY_LAYER=10;var _n=$t,ur=new Set(["1.0","1.0-beta"]),dr=class{get name(){return"VRMFirstPersonLoaderPlugin"}constructor(e){this.parser=e}afterRoot(e){return I(this,null,function*(){const t=e.userData.vrmHumanoid;if(t!==null){if(t===void 0)throw new Error("VRMFirstPersonLoaderPlugin: vrmHumanoid is undefined. VRMHumanoidLoaderPlugin have to be used first");e.userData.vrmFirstPerson=yield this._import(e,t)}})}_import(e,t){return I(this,null,function*(){if(t==null)return null;const n=yield this._v1Import(e,t);if(n)return n;const i=yield this._v0Import(e,t);return i||null})}_v1Import(e,t){return I(this,null,function*(){var n,i;const r=this.parser.json;if(!(((n=r.extensionsUsed)==null?void 0:n.indexOf("VRMC_vrm"))!==-1))return null;const s=(i=r.extensions)==null?void 0:i.VRMC_vrm;if(!s)return null;const l=s.specVersion;if(!ur.has(l))return console.warn(`VRMFirstPersonLoaderPlugin: Unknown VRMC_vrm specVersion "${l}"`),null;const a=s.firstPerson,u=[],d=yield hn(e);return Array.from(d.entries()).forEach(([c,h])=>{var p,f;const m=(p=a?.meshAnnotations)==null?void 0:p.find(_=>_.node===c);u.push({meshes:h,type:(f=m?.type)!=null?f:"auto"})}),new _n(t,u)})}_v0Import(e,t){return I(this,null,function*(){var n;const i=this.parser.json,r=(n=i.extensions)==null?void 0:n.VRM;if(!r)return null;const o=r.firstPerson;if(!o)return null;const s=[],l=yield hn(e);return Array.from(l.entries()).forEach(([a,u])=>{const d=i.nodes[a],c=o.meshAnnotations?o.meshAnnotations.find(h=>h.mesh===d.mesh):void 0;s.push({meshes:u,type:this._convertV0FlagToV1Type(c?.firstPersonFlag)})}),new _n(t,s)})}_convertV0FlagToV1Type(e){return e==="FirstPersonOnly"?"firstPersonOnly":e==="ThirdPersonOnly"?"thirdPersonOnly":e==="Both"?"both":"auto"}},vn=new v,Mn=new v,cr=new A,xn=class extends Xe{constructor(e){super(),this.vrmHumanoid=e,this._boneAxesMap=new Map,Object.values(e.humanBones).forEach(t=>{const n=new Gi(1);n.matrixAutoUpdate=!1,n.material.depthTest=!1,n.material.depthWrite=!1,this.add(n),this._boneAxesMap.set(t,n)})}dispose(){Array.from(this._boneAxesMap.values()).forEach(e=>{e.geometry.dispose(),e.material.dispose()})}updateMatrixWorld(e){Array.from(this._boneAxesMap.entries()).forEach(([t,n])=>{t.node.updateWorldMatrix(!0,!1),t.node.matrixWorld.decompose(vn,cr,Mn);const i=vn.set(.1,.1,.1).divide(Mn);n.matrix.copy(t.node.matrixWorld).scale(i)}),super.updateMatrixWorld(e)}},Et=["hips","spine","chest","upperChest","neck","head","leftEye","rightEye","jaw","leftUpperLeg","leftLowerLeg","leftFoot","leftToes","rightUpperLeg","rightLowerLeg","rightFoot","rightToes","leftShoulder","leftUpperArm","leftLowerArm","leftHand","rightShoulder","rightUpperArm","rightLowerArm","rightHand","leftThumbMetacarpal","leftThumbProximal","leftThumbDistal","leftIndexProximal","leftIndexIntermediate","leftIndexDistal","leftMiddleProximal","leftMiddleIntermediate","leftMiddleDistal","leftRingProximal","leftRingIntermediate","leftRingDistal","leftLittleProximal","leftLittleIntermediate","leftLittleDistal","rightThumbMetacarpal","rightThumbProximal","rightThumbDistal","rightIndexProximal","rightIndexIntermediate","rightIndexDistal","rightMiddleProximal","rightMiddleIntermediate","rightMiddleDistal","rightRingProximal","rightRingIntermediate","rightRingDistal","rightLittleProximal","rightLittleIntermediate","rightLittleDistal"],hr={hips:null,spine:"hips",chest:"spine",upperChest:"chest",neck:"upperChest",head:"neck",leftEye:"head",rightEye:"head",jaw:"head",leftUpperLeg:"hips",leftLowerLeg:"leftUpperLeg",leftFoot:"leftLowerLeg",leftToes:"leftFoot",rightUpperLeg:"hips",rightLowerLeg:"rightUpperLeg",rightFoot:"rightLowerLeg",rightToes:"rightFoot",leftShoulder:"upperChest",leftUpperArm:"leftShoulder",leftLowerArm:"leftUpperArm",leftHand:"leftLowerArm",rightShoulder:"upperChest",rightUpperArm:"rightShoulder",rightLowerArm:"rightUpperArm",rightHand:"rightLowerArm",leftThumbMetacarpal:"leftHand",leftThumbProximal:"leftThumbMetacarpal",leftThumbDistal:"leftThumbProximal",leftIndexProximal:"leftHand",leftIndexIntermediate:"leftIndexProximal",leftIndexDistal:"leftIndexIntermediate",leftMiddleProximal:"leftHand",leftMiddleIntermediate:"leftMiddleProximal",leftMiddleDistal:"leftMiddleIntermediate",leftRingProximal:"leftHand",leftRingIntermediate:"leftRingProximal",leftRingDistal:"leftRingIntermediate",leftLittleProximal:"leftHand",leftLittleIntermediate:"leftLittleProximal",leftLittleDistal:"leftLittleIntermediate",rightThumbMetacarpal:"rightHand",rightThumbProximal:"rightThumbMetacarpal",rightThumbDistal:"rightThumbProximal",rightIndexProximal:"rightHand",rightIndexIntermediate:"rightIndexProximal",rightIndexDistal:"rightIndexIntermediate",rightMiddleProximal:"rightHand",rightMiddleIntermediate:"rightMiddleProximal",rightMiddleDistal:"rightMiddleIntermediate",rightRingProximal:"rightHand",rightRingIntermediate:"rightRingProximal",rightRingDistal:"rightRingIntermediate",rightLittleProximal:"rightHand",rightLittleIntermediate:"rightLittleProximal",rightLittleDistal:"rightLittleIntermediate"};function di(e){return e.invert?e.invert():e.inverse(),e}var Ue=new v,Ne=new A,Wt=class{constructor(e){this.humanBones=e,this.restPose=this.getAbsolutePose()}getAbsolutePose(){const e={};return Object.keys(this.humanBones).forEach(t=>{const n=t,i=this.getBoneNode(n);i&&(Ue.copy(i.position),Ne.copy(i.quaternion),e[n]={position:Ue.toArray(),rotation:Ne.toArray()})}),e}getPose(){const e={};return Object.keys(this.humanBones).forEach(t=>{const n=t,i=this.getBoneNode(n);if(!i)return;Ue.set(0,0,0),Ne.identity();const r=this.restPose[n];r?.position&&Ue.fromArray(r.position).negate(),r?.rotation&&di(Ne.fromArray(r.rotation)),Ue.add(i.position),Ne.premultiply(i.quaternion),e[n]={position:Ue.toArray(),rotation:Ne.toArray()}}),e}setPose(e){Object.entries(e).forEach(([t,n])=>{const i=t,r=this.getBoneNode(i);if(!r)return;const o=this.restPose[i];o&&(n?.position&&(r.position.fromArray(n.position),o.position&&r.position.add(Ue.fromArray(o.position))),n?.rotation&&(r.quaternion.fromArray(n.rotation),o.rotation&&r.quaternion.multiply(Ne.fromArray(o.rotation))))})}resetPose(){Object.entries(this.restPose).forEach(([e,t])=>{const n=this.getBoneNode(e);n&&(t?.position&&n.position.fromArray(t.position),t?.rotation&&n.quaternion.fromArray(t.rotation))})}getBone(e){var t;return(t=this.humanBones[e])!=null?t:void 0}getBoneNode(e){var t,n;return(n=(t=this.humanBones[e])==null?void 0:t.node)!=null?n:null}},Pt=new v,pr=new A,fr=new v,wn=class ci extends Wt{static _setupTransforms(t){const n=new at;n.name="VRMHumanoidRig";const i={},r={},o={};Et.forEach(l=>{var a;const u=t.getBoneNode(l);if(u){const d=new v,c=new A;u.updateWorldMatrix(!0,!1),u.matrixWorld.decompose(d,c,Pt),i[l]=d,r[l]=u.quaternion.clone();const h=new A;(a=u.parent)==null||a.matrixWorld.decompose(Pt,h,Pt),o[l]=h}});const s={};return Et.forEach(l=>{var a;const u=t.getBoneNode(l);if(u){const d=i[l];let c=l,h;for(;h==null&&(c=hr[c],c!=null);)h=i[c];const p=new at;p.name="Normalized_"+u.name,(c?(a=s[c])==null?void 0:a.node:n).add(p),p.position.copy(d),h&&p.position.sub(h),s[l]={node:p}}}),{rigBones:s,root:n,parentWorldRotations:o,boneRotations:r}}constructor(t){const{rigBones:n,root:i,parentWorldRotations:r,boneRotations:o}=ci._setupTransforms(t);super(n),this.original=t,this.root=i,this._parentWorldRotations=r,this._boneRotations=o}update(){Et.forEach(t=>{const n=this.original.getBoneNode(t);if(n!=null){const i=this.getBoneNode(t),r=this._parentWorldRotations[t],o=pr.copy(r).invert(),s=this._boneRotations[t];if(n.quaternion.copy(i.quaternion).multiply(r).premultiply(o).multiply(s),t==="hips"){const l=i.getWorldPosition(fr);n.parent.updateWorldMatrix(!0,!1);const a=n.parent.matrixWorld,u=l.applyMatrix4(a.invert());n.position.copy(u)}}})}},yn=class hi{get restPose(){return console.warn("VRMHumanoid: restPose is deprecated. Use either rawRestPose or normalizedRestPose instead."),this.rawRestPose}get rawRestPose(){return this._rawHumanBones.restPose}get normalizedRestPose(){return this._normalizedHumanBones.restPose}get humanBones(){return this._rawHumanBones.humanBones}get rawHumanBones(){return this._rawHumanBones.humanBones}get normalizedHumanBones(){return this._normalizedHumanBones.humanBones}get normalizedHumanBonesRoot(){return this._normalizedHumanBones.root}constructor(t,n){var i;this.autoUpdateHumanBones=(i=n?.autoUpdateHumanBones)!=null?i:!0,this._rawHumanBones=new Wt(t),this._normalizedHumanBones=new wn(this._rawHumanBones)}copy(t){return this.autoUpdateHumanBones=t.autoUpdateHumanBones,this._rawHumanBones=new Wt(t.humanBones),this._normalizedHumanBones=new wn(this._rawHumanBones),this}clone(){return new hi(this.humanBones,{autoUpdateHumanBones:this.autoUpdateHumanBones}).copy(this)}getAbsolutePose(){return console.warn("VRMHumanoid: getAbsolutePose() is deprecated. Use either getRawAbsolutePose() or getNormalizedAbsolutePose() instead."),this.getRawAbsolutePose()}getRawAbsolutePose(){return this._rawHumanBones.getAbsolutePose()}getNormalizedAbsolutePose(){return this._normalizedHumanBones.getAbsolutePose()}getPose(){return console.warn("VRMHumanoid: getPose() is deprecated. Use either getRawPose() or getNormalizedPose() instead."),this.getRawPose()}getRawPose(){return this._rawHumanBones.getPose()}getNormalizedPose(){return this._normalizedHumanBones.getPose()}setPose(t){return console.warn("VRMHumanoid: setPose() is deprecated. Use either setRawPose() or setNormalizedPose() instead."),this.setRawPose(t)}setRawPose(t){return this._rawHumanBones.setPose(t)}setNormalizedPose(t){return this._normalizedHumanBones.setPose(t)}resetPose(){return console.warn("VRMHumanoid: resetPose() is deprecated. Use either resetRawPose() or resetNormalizedPose() instead."),this.resetRawPose()}resetRawPose(){return this._rawHumanBones.resetPose()}resetNormalizedPose(){return this._normalizedHumanBones.resetPose()}getBone(t){return console.warn("VRMHumanoid: getBone() is deprecated. Use either getRawBone() or getNormalizedBone() instead."),this.getRawBone(t)}getRawBone(t){return this._rawHumanBones.getBone(t)}getNormalizedBone(t){return this._normalizedHumanBones.getBone(t)}getBoneNode(t){return console.warn("VRMHumanoid: getBoneNode() is deprecated. Use either getRawBoneNode() or getNormalizedBoneNode() instead."),this.getRawBoneNode(t)}getRawBoneNode(t){return this._rawHumanBones.getBoneNode(t)}getNormalizedBoneNode(t){return this._normalizedHumanBones.getBoneNode(t)}update(){this.autoUpdateHumanBones&&this._normalizedHumanBones.update()}},mr={Hips:"hips",Spine:"spine",Head:"head",LeftUpperLeg:"leftUpperLeg",LeftLowerLeg:"leftLowerLeg",LeftFoot:"leftFoot",RightUpperLeg:"rightUpperLeg",RightLowerLeg:"rightLowerLeg",RightFoot:"rightFoot",LeftUpperArm:"leftUpperArm",LeftLowerArm:"leftLowerArm",LeftHand:"leftHand",RightUpperArm:"rightUpperArm",RightLowerArm:"rightLowerArm",RightHand:"rightHand"},gr=new Set(["1.0","1.0-beta"]),Rn={leftThumbProximal:"leftThumbMetacarpal",leftThumbIntermediate:"leftThumbProximal",rightThumbProximal:"rightThumbMetacarpal",rightThumbIntermediate:"rightThumbProximal"},_r=class{get name(){return"VRMHumanoidLoaderPlugin"}constructor(e,t){this.parser=e,this.helperRoot=t?.helperRoot,this.autoUpdateHumanBones=t?.autoUpdateHumanBones}afterRoot(e){return I(this,null,function*(){e.userData.vrmHumanoid=yield this._import(e)})}_import(e){return I(this,null,function*(){const t=yield this._v1Import(e);if(t)return t;const n=yield this._v0Import(e);return n||null})}_v1Import(e){return I(this,null,function*(){var t,n;const i=this.parser.json;if(!(((t=i.extensionsUsed)==null?void 0:t.indexOf("VRMC_vrm"))!==-1))return null;const o=(n=i.extensions)==null?void 0:n.VRMC_vrm;if(!o)return null;const s=o.specVersion;if(!gr.has(s))return console.warn(`VRMHumanoidLoaderPlugin: Unknown VRMC_vrm specVersion "${s}"`),null;const l=o.humanoid;if(!l)return null;const a=l.humanBones.leftThumbIntermediate!=null||l.humanBones.rightThumbIntermediate!=null,u={};l.humanBones!=null&&(yield Promise.all(Object.entries(l.humanBones).map(c=>I(this,[c],function*([h,p]){let f=h;const m=p.node;if(a){const g=Rn[f];g!=null&&(f=g)}const _=yield this.parser.getDependency("node",m);if(_==null){console.warn(`A glTF node bound to the humanoid bone ${f} (index = ${m}) does not exist`);return}u[f]={node:_}}))));const d=new yn(this._ensureRequiredBonesExist(u),{autoUpdateHumanBones:this.autoUpdateHumanBones});if(e.scene.add(d.normalizedHumanBonesRoot),this.helperRoot){const c=new xn(d);this.helperRoot.add(c),c.renderOrder=this.helperRoot.renderOrder}return d})}_v0Import(e){return I(this,null,function*(){var t;const i=(t=this.parser.json.extensions)==null?void 0:t.VRM;if(!i)return null;const r=i.humanoid;if(!r)return null;const o={};r.humanBones!=null&&(yield Promise.all(r.humanBones.map(l=>I(this,null,function*(){const a=l.bone,u=l.node;if(a==null||u==null)return;if(u<0){console.warn(`A glTF node index for the humanoid bone ${a} is negative (${u}), ignoring this bone.`);return}const d=yield this.parser.getDependency("node",u);if(d==null){console.warn(`A glTF node bound to the humanoid bone ${a} (index = ${u}) does not exist`);return}const c=Rn[a],h=c??a;if(o[h]!=null){console.warn(`Multiple bone entries for ${h} detected (index = ${u}), ignoring duplicated entries.`);return}o[h]={node:d}}))));const s=new yn(this._ensureRequiredBonesExist(o),{autoUpdateHumanBones:this.autoUpdateHumanBones});if(e.scene.add(s.normalizedHumanBonesRoot),this.helperRoot){const l=new xn(s);this.helperRoot.add(l),l.renderOrder=this.helperRoot.renderOrder}return s})}_ensureRequiredBonesExist(e){const t=Object.values(mr).filter(n=>e[n]==null);if(t.length>0)throw new Error(`VRMHumanoidLoaderPlugin: These humanoid bones are required but not exist: ${t.join(", ")}`);return e}},Tn=class extends ve{constructor(){super(),this._currentTheta=0,this._currentRadius=0,this.theta=0,this.radius=0,this._currentTheta=0,this._currentRadius=0,this._attrPos=new X(new Float32Array(65*3),3),this.setAttribute("position",this._attrPos),this._attrIndex=new X(new Uint16Array(3*63),1),this.setIndex(this._attrIndex),this._buildIndex(),this.update()}update(){let e=!1;this._currentTheta!==this.theta&&(this._currentTheta=this.theta,e=!0),this._currentRadius!==this.radius&&(this._currentRadius=this.radius,e=!0),e&&this._buildPosition()}_buildPosition(){this._attrPos.setXYZ(0,0,0,0);for(let e=0;e<64;e++){const t=e/63*this._currentTheta;this._attrPos.setXYZ(e+1,this._currentRadius*Math.sin(t),0,this._currentRadius*Math.cos(t))}this._attrPos.needsUpdate=!0}_buildIndex(){for(let e=0;e<63;e++)this._attrIndex.setXYZ(e*3,0,e+1,e+2);this._attrIndex.needsUpdate=!0}},vr=class extends ve{constructor(){super(),this.radius=0,this._currentRadius=0,this.tail=new v,this._currentTail=new v,this._attrPos=new X(new Float32Array(294),3),this.setAttribute("position",this._attrPos),this._attrIndex=new X(new Uint16Array(194),1),this.setIndex(this._attrIndex),this._buildIndex(),this.update()}update(){let e=!1;this._currentRadius!==this.radius&&(this._currentRadius=this.radius,e=!0),this._currentTail.equals(this.tail)||(this._currentTail.copy(this.tail),e=!0),e&&this._buildPosition()}_buildPosition(){for(let e=0;e<32;e++){const t=e/16*Math.PI;this._attrPos.setXYZ(e,Math.cos(t),Math.sin(t),0),this._attrPos.setXYZ(32+e,0,Math.cos(t),Math.sin(t)),this._attrPos.setXYZ(64+e,Math.sin(t),0,Math.cos(t))}this.scale(this._currentRadius,this._currentRadius,this._currentRadius),this.translate(this._currentTail.x,this._currentTail.y,this._currentTail.z),this._attrPos.setXYZ(96,0,0,0),this._attrPos.setXYZ(97,this._currentTail.x,this._currentTail.y,this._currentTail.z),this._attrPos.needsUpdate=!0}_buildIndex(){for(let e=0;e<32;e++){const t=(e+1)%32;this._attrIndex.setXY(e*2,e,t),this._attrIndex.setXY(64+e*2,32+e,32+t),this._attrIndex.setXY(128+e*2,64+e,64+t)}this._attrIndex.setXY(192,96,97),this._attrIndex.needsUpdate=!0}},ht=new A,Sn=new A,tt=new v,An=new v,En=Math.sqrt(2)/2,Mr=new A(0,0,-En,En),xr=new v(0,1,0),wr=class extends Xe{constructor(e){super(),this.matrixAutoUpdate=!1,this.vrmLookAt=e;{const t=new Tn;t.radius=.5;const n=new rn({color:65280,transparent:!0,opacity:.5,side:on,depthTest:!1,depthWrite:!1});this._meshPitch=new sn(t,n),this.add(this._meshPitch)}{const t=new Tn;t.radius=.5;const n=new rn({color:16711680,transparent:!0,opacity:.5,side:on,depthTest:!1,depthWrite:!1});this._meshYaw=new sn(t,n),this.add(this._meshYaw)}{const t=new vr;t.radius=.1;const n=new Rt({color:16777215,depthTest:!1,depthWrite:!1});this._lineTarget=new Yt(t,n),this._lineTarget.frustumCulled=!1,this.add(this._lineTarget)}}dispose(){this._meshYaw.geometry.dispose(),this._meshYaw.material.dispose(),this._meshPitch.geometry.dispose(),this._meshPitch.material.dispose(),this._lineTarget.geometry.dispose(),this._lineTarget.material.dispose()}updateMatrixWorld(e){const t=V.DEG2RAD*this.vrmLookAt.yaw;this._meshYaw.geometry.theta=t,this._meshYaw.geometry.update();const n=V.DEG2RAD*this.vrmLookAt.pitch;this._meshPitch.geometry.theta=n,this._meshPitch.geometry.update(),this.vrmLookAt.getLookAtWorldPosition(tt),this.vrmLookAt.getLookAtWorldQuaternion(ht),ht.multiply(this.vrmLookAt.getFaceFrontQuaternion(Sn)),this._meshYaw.position.copy(tt),this._meshYaw.quaternion.copy(ht),this._meshPitch.position.copy(tt),this._meshPitch.quaternion.copy(ht),this._meshPitch.quaternion.multiply(Sn.setFromAxisAngle(xr,t)),this._meshPitch.quaternion.multiply(Mr);const{target:i,autoUpdate:r}=this.vrmLookAt;i!=null&&r&&(i.getWorldPosition(An).sub(tt),this._lineTarget.geometry.tail.copy(An),this._lineTarget.geometry.update(),this._lineTarget.position.copy(tt)),super.updateMatrixWorld(e)}},yr=new v,Rr=new v;function zt(e,t){return e.matrixWorld.decompose(yr,t,Rr),t}function mt(e){return[Math.atan2(-e.z,e.x),Math.atan2(e.y,Math.sqrt(e.x*e.x+e.z*e.z))]}function Pn(e){const t=Math.round(e/2/Math.PI);return e-2*Math.PI*t}var Ln=new v(0,0,1),Tr=new v,Sr=new v,Ar=new v,Er=new A,Lt=new A,bn=new A,Pr=new A,bt=new Gt,pi=class fi{constructor(t,n){this.offsetFromHeadBone=new v,this.autoUpdate=!0,this.faceFront=new v(0,0,1),this.humanoid=t,this.applier=n,this._yaw=0,this._pitch=0,this._needsUpdate=!0,this._restHeadWorldQuaternion=this.getLookAtWorldQuaternion(new A)}get yaw(){return this._yaw}set yaw(t){this._yaw=t,this._needsUpdate=!0}get pitch(){return this._pitch}set pitch(t){this._pitch=t,this._needsUpdate=!0}get euler(){return console.warn("VRMLookAt: euler is deprecated. use getEuler() instead."),this.getEuler(new Gt)}getEuler(t){return t.set(V.DEG2RAD*this._pitch,V.DEG2RAD*this._yaw,0,"YXZ")}copy(t){if(this.humanoid!==t.humanoid)throw new Error("VRMLookAt: humanoid must be same in order to copy");return this.offsetFromHeadBone.copy(t.offsetFromHeadBone),this.applier=t.applier,this.autoUpdate=t.autoUpdate,this.target=t.target,this.faceFront.copy(t.faceFront),this}clone(){return new fi(this.humanoid,this.applier).copy(this)}reset(){this._yaw=0,this._pitch=0,this._needsUpdate=!0}getLookAtWorldPosition(t){const n=this.humanoid.getRawBoneNode("head");return t.copy(this.offsetFromHeadBone).applyMatrix4(n.matrixWorld)}getLookAtWorldQuaternion(t){const n=this.humanoid.getRawBoneNode("head");return zt(n,t)}getFaceFrontQuaternion(t){if(this.faceFront.distanceToSquared(Ln)<.01)return t.copy(this._restHeadWorldQuaternion).invert();const[n,i]=mt(this.faceFront);return bt.set(0,.5*Math.PI+n,i,"YZX"),t.setFromEuler(bt).premultiply(Pr.copy(this._restHeadWorldQuaternion).invert())}getLookAtWorldDirection(t){return this.getLookAtWorldQuaternion(Lt),this.getFaceFrontQuaternion(bn),t.copy(Ln).applyQuaternion(Lt).applyQuaternion(bn).applyEuler(this.getEuler(bt))}lookAt(t){const n=Er.copy(this._restHeadWorldQuaternion).multiply(di(this.getLookAtWorldQuaternion(Lt))),i=this.getLookAtWorldPosition(Sr),r=Ar.copy(t).sub(i).applyQuaternion(n).normalize(),[o,s]=mt(this.faceFront),[l,a]=mt(r),u=Pn(l-o),d=Pn(s-a);this._yaw=V.RAD2DEG*u,this._pitch=V.RAD2DEG*d,this._needsUpdate=!0}update(t){this.target!=null&&this.autoUpdate&&this.lookAt(this.target.getWorldPosition(Tr)),this._needsUpdate&&(this._needsUpdate=!1,this.applier.applyYawPitch(this._yaw,this._pitch))}};pi.EULER_ORDER="YXZ";var Lr=pi,br=new v(0,0,1),ae=new A,Fe=new A,te=new Gt(0,0,0,"YXZ"),gt=class{constructor(e,t,n,i,r){this.humanoid=e,this.rangeMapHorizontalInner=t,this.rangeMapHorizontalOuter=n,this.rangeMapVerticalDown=i,this.rangeMapVerticalUp=r,this.faceFront=new v(0,0,1),this._restQuatLeftEye=new A,this._restQuatRightEye=new A,this._restLeftEyeParentWorldQuat=new A,this._restRightEyeParentWorldQuat=new A;const o=this.humanoid.getRawBoneNode("leftEye"),s=this.humanoid.getRawBoneNode("rightEye");o&&(this._restQuatLeftEye.copy(o.quaternion),zt(o.parent,this._restLeftEyeParentWorldQuat)),s&&(this._restQuatRightEye.copy(s.quaternion),zt(s.parent,this._restRightEyeParentWorldQuat))}applyYawPitch(e,t){const n=this.humanoid.getRawBoneNode("leftEye"),i=this.humanoid.getRawBoneNode("rightEye"),r=this.humanoid.getNormalizedBoneNode("leftEye"),o=this.humanoid.getNormalizedBoneNode("rightEye");n&&(t<0?te.x=-V.DEG2RAD*this.rangeMapVerticalDown.map(-t):te.x=V.DEG2RAD*this.rangeMapVerticalUp.map(t),e<0?te.y=-V.DEG2RAD*this.rangeMapHorizontalInner.map(-e):te.y=V.DEG2RAD*this.rangeMapHorizontalOuter.map(e),ae.setFromEuler(te),this._getWorldFaceFrontQuat(Fe),r.quaternion.copy(Fe).multiply(ae).multiply(Fe.invert()),ae.copy(this._restLeftEyeParentWorldQuat),n.quaternion.copy(r.quaternion).multiply(ae).premultiply(ae.invert()).multiply(this._restQuatLeftEye)),i&&(t<0?te.x=-V.DEG2RAD*this.rangeMapVerticalDown.map(-t):te.x=V.DEG2RAD*this.rangeMapVerticalUp.map(t),e<0?te.y=-V.DEG2RAD*this.rangeMapHorizontalOuter.map(-e):te.y=V.DEG2RAD*this.rangeMapHorizontalInner.map(e),ae.setFromEuler(te),this._getWorldFaceFrontQuat(Fe),o.quaternion.copy(Fe).multiply(ae).multiply(Fe.invert()),ae.copy(this._restRightEyeParentWorldQuat),i.quaternion.copy(o.quaternion).multiply(ae).premultiply(ae.invert()).multiply(this._restQuatRightEye))}lookAt(e){console.warn("VRMLookAtBoneApplier: lookAt() is deprecated. use apply() instead.");const t=V.RAD2DEG*e.y,n=V.RAD2DEG*e.x;this.applyYawPitch(t,n)}_getWorldFaceFrontQuat(e){if(this.faceFront.distanceToSquared(br)<.01)return e.identity();const[t,n]=mt(this.faceFront);return te.set(0,.5*Math.PI+t,n,"YZX"),e.setFromEuler(te)}};gt.type="bone";var jt=class{constructor(e,t,n,i,r){this.expressions=e,this.rangeMapHorizontalInner=t,this.rangeMapHorizontalOuter=n,this.rangeMapVerticalDown=i,this.rangeMapVerticalUp=r}applyYawPitch(e,t){t<0?(this.expressions.setValue("lookDown",0),this.expressions.setValue("lookUp",this.rangeMapVerticalUp.map(-t))):(this.expressions.setValue("lookUp",0),this.expressions.setValue("lookDown",this.rangeMapVerticalDown.map(t))),e<0?(this.expressions.setValue("lookLeft",0),this.expressions.setValue("lookRight",this.rangeMapHorizontalOuter.map(-e))):(this.expressions.setValue("lookRight",0),this.expressions.setValue("lookLeft",this.rangeMapHorizontalOuter.map(e)))}lookAt(e){console.warn("VRMLookAtBoneApplier: lookAt() is deprecated. use apply() instead.");const t=V.RAD2DEG*e.y,n=V.RAD2DEG*e.x;this.applyYawPitch(t,n)}};jt.type="expression";var In=class{constructor(e,t){this.inputMaxValue=e,this.outputScale=t}map(e){return this.outputScale*ni(e/this.inputMaxValue)}},Ir=new Set(["1.0","1.0-beta"]),pt=.01,Cr=class{get name(){return"VRMLookAtLoaderPlugin"}constructor(e,t){this.parser=e,this.helperRoot=t?.helperRoot}afterRoot(e){return I(this,null,function*(){const t=e.userData.vrmHumanoid;if(t===null)return;if(t===void 0)throw new Error("VRMLookAtLoaderPlugin: vrmHumanoid is undefined. VRMHumanoidLoaderPlugin have to be used first");const n=e.userData.vrmExpressionManager;if(n!==null){if(n===void 0)throw new Error("VRMLookAtLoaderPlugin: vrmExpressionManager is undefined. VRMExpressionLoaderPlugin have to be used first");e.userData.vrmLookAt=yield this._import(e,t,n)}})}_import(e,t,n){return I(this,null,function*(){if(t==null||n==null)return null;const i=yield this._v1Import(e,t,n);if(i)return i;const r=yield this._v0Import(e,t,n);return r||null})}_v1Import(e,t,n){return I(this,null,function*(){var i,r,o;const s=this.parser.json;if(!(((i=s.extensionsUsed)==null?void 0:i.indexOf("VRMC_vrm"))!==-1))return null;const a=(r=s.extensions)==null?void 0:r.VRMC_vrm;if(!a)return null;const u=a.specVersion;if(!Ir.has(u))return console.warn(`VRMLookAtLoaderPlugin: Unknown VRMC_vrm specVersion "${u}"`),null;const d=a.lookAt;if(!d)return null;const c=d.type==="expression"?1:10,h=this._v1ImportRangeMap(d.rangeMapHorizontalInner,c),p=this._v1ImportRangeMap(d.rangeMapHorizontalOuter,c),f=this._v1ImportRangeMap(d.rangeMapVerticalDown,c),m=this._v1ImportRangeMap(d.rangeMapVerticalUp,c);let _;d.type==="expression"?_=new jt(n,h,p,f,m):_=new gt(t,h,p,f,m);const g=this._importLookAt(t,_);return g.offsetFromHeadBone.fromArray((o=d.offsetFromHeadBone)!=null?o:[0,.06,0]),g})}_v1ImportRangeMap(e,t){var n,i;let r=(n=e?.inputMaxValue)!=null?n:90;const o=(i=e?.outputScale)!=null?i:t;return r<pt&&(console.warn("VRMLookAtLoaderPlugin: inputMaxValue of a range map is too small. Consider reviewing the range map!"),r=pt),new In(r,o)}_v0Import(e,t,n){return I(this,null,function*(){var i,r,o,s;const a=(i=this.parser.json.extensions)==null?void 0:i.VRM;if(!a)return null;const u=a.firstPerson;if(!u)return null;const d=u.lookAtTypeName==="BlendShape"?1:10,c=this._v0ImportDegreeMap(u.lookAtHorizontalInner,d),h=this._v0ImportDegreeMap(u.lookAtHorizontalOuter,d),p=this._v0ImportDegreeMap(u.lookAtVerticalDown,d),f=this._v0ImportDegreeMap(u.lookAtVerticalUp,d);let m;u.lookAtTypeName==="BlendShape"?m=new jt(n,c,h,p,f):m=new gt(t,c,h,p,f);const _=this._importLookAt(t,m);return u.firstPersonBoneOffset?_.offsetFromHeadBone.set((r=u.firstPersonBoneOffset.x)!=null?r:0,(o=u.firstPersonBoneOffset.y)!=null?o:.06,-((s=u.firstPersonBoneOffset.z)!=null?s:0)):_.offsetFromHeadBone.set(0,.06,0),_.faceFront.set(0,0,-1),m instanceof gt&&m.faceFront.set(0,0,-1),_})}_v0ImportDegreeMap(e,t){var n,i;const r=e?.curve;JSON.stringify(r)!=="[0,0,0,1,1,1,1,0]"&&console.warn("Curves of LookAtDegreeMap defined in VRM 0.0 are not supported");let o=(n=e?.xRange)!=null?n:90;const s=(i=e?.yRange)!=null?i:t;return o<pt&&(console.warn("VRMLookAtLoaderPlugin: xRange of a degree map is too small. Consider reviewing the degree map!"),o=pt),new In(o,s)}_importLookAt(e,t){const n=new Lr(e,t);if(this.helperRoot){const i=new wr(n);this.helperRoot.add(i),i.renderOrder=this.helperRoot.renderOrder}return n}};function Or(e,t){return typeof e!="string"||e===""?"":(/^https?:\/\//i.test(t)&&/^\//.test(e)&&(t=t.replace(/(^https?:\/\/[^/]+).*/i,"$1")),/^(https?:)?\/\//i.test(e)||/^data:.*,.*$/i.test(e)||/^blob:.*$/i.test(e)?e:t+e)}var Ur=new Set(["1.0","1.0-beta"]),Nr=class{get name(){return"VRMMetaLoaderPlugin"}constructor(e,t){var n,i,r;this.parser=e,this.needThumbnailImage=(n=t?.needThumbnailImage)!=null?n:!1,this.acceptLicenseUrls=(i=t?.acceptLicenseUrls)!=null?i:["https://vrm.dev/licenses/1.0/"],this.acceptV0Meta=(r=t?.acceptV0Meta)!=null?r:!0}afterRoot(e){return I(this,null,function*(){e.userData.vrmMeta=yield this._import(e)})}_import(e){return I(this,null,function*(){const t=yield this._v1Import(e);if(t!=null)return t;const n=yield this._v0Import(e);return n??null})}_v1Import(e){return I(this,null,function*(){var t,n,i;const r=this.parser.json;if(!(((t=r.extensionsUsed)==null?void 0:t.indexOf("VRMC_vrm"))!==-1))return null;const s=(n=r.extensions)==null?void 0:n.VRMC_vrm;if(s==null)return null;const l=s.specVersion;if(!Ur.has(l))return console.warn(`VRMMetaLoaderPlugin: Unknown VRMC_vrm specVersion "${l}"`),null;const a=s.meta;if(!a)return null;const u=a.licenseUrl;if(!new Set(this.acceptLicenseUrls).has(u))throw new Error(`VRMMetaLoaderPlugin: The license url "${u}" is not accepted`);let c;return this.needThumbnailImage&&a.thumbnailImage!=null&&(c=(i=yield this._extractGLTFImage(a.thumbnailImage))!=null?i:void 0),{metaVersion:"1",name:a.name,version:a.version,authors:a.authors,copyrightInformation:a.copyrightInformation,contactInformation:a.contactInformation,references:a.references,thirdPartyLicenses:a.thirdPartyLicenses,thumbnailImage:c,licenseUrl:a.licenseUrl,avatarPermission:a.avatarPermission,allowExcessivelyViolentUsage:a.allowExcessivelyViolentUsage,allowExcessivelySexualUsage:a.allowExcessivelySexualUsage,commercialUsage:a.commercialUsage,allowPoliticalOrReligiousUsage:a.allowPoliticalOrReligiousUsage,allowAntisocialOrHateUsage:a.allowAntisocialOrHateUsage,creditNotation:a.creditNotation,allowRedistribution:a.allowRedistribution,modification:a.modification,otherLicenseUrl:a.otherLicenseUrl}})}_v0Import(e){return I(this,null,function*(){var t;const i=(t=this.parser.json.extensions)==null?void 0:t.VRM;if(!i)return null;const r=i.meta;if(!r)return null;if(!this.acceptV0Meta)throw new Error("VRMMetaLoaderPlugin: Attempted to load VRM0.0 meta but acceptV0Meta is false");let o;return this.needThumbnailImage&&r.texture!=null&&r.texture!==-1&&(o=yield this.parser.getDependency("texture",r.texture)),{metaVersion:"0",allowedUserName:r.allowedUserName,author:r.author,commercialUssageName:r.commercialUssageName,contactInformation:r.contactInformation,licenseName:r.licenseName,otherLicenseUrl:r.otherLicenseUrl,otherPermissionUrl:r.otherPermissionUrl,reference:r.reference,sexualUssageName:r.sexualUssageName,texture:o??void 0,title:r.title,version:r.version,violentUssageName:r.violentUssageName}})}_extractGLTFImage(e){return I(this,null,function*(){var t;const i=(t=this.parser.json.images)==null?void 0:t[e];if(i==null)return console.warn(`VRMMetaLoaderPlugin: Attempt to use images[${e}] of glTF as a thumbnail but the image doesn't exist`),null;let r=i.uri;if(i.bufferView!=null){const s=yield this.parser.getDependency("bufferView",i.bufferView),l=new Blob([s],{type:i.mimeType});r=URL.createObjectURL(l)}return r==null?(console.warn(`VRMMetaLoaderPlugin: Attempt to use images[${e}] of glTF as a thumbnail but the image couldn't load properly`),null):yield new Fi().loadAsync(Or(r,this.parser.options.path)).catch(s=>(console.warn("VRMMetaLoaderPlugin: Failed to load a thumbnail image"),null))})}},Vr=class{constructor(e){this.scene=e.scene,this.meta=e.meta,this.humanoid=e.humanoid,this.expressionManager=e.expressionManager,this.firstPerson=e.firstPerson,this.lookAt=e.lookAt}update(e){this.humanoid.update(),this.lookAt&&this.lookAt.update(e),this.expressionManager&&this.expressionManager.update()}},Br=class extends Vr{constructor(e){super(e),this.materials=e.materials,this.springBoneManager=e.springBoneManager,this.nodeConstraintManager=e.nodeConstraintManager}update(e){super.update(e),this.nodeConstraintManager&&this.nodeConstraintManager.update(),this.springBoneManager&&this.springBoneManager.update(e),this.materials&&this.materials.forEach(t=>{t.update&&t.update(e)})}},Dr=Object.defineProperty,Cn=Object.getOwnPropertySymbols,kr=Object.prototype.hasOwnProperty,Fr=Object.prototype.propertyIsEnumerable,On=(e,t,n)=>t in e?Dr(e,t,{enumerable:!0,configurable:!0,writable:!0,value:n}):e[t]=n,Un=(e,t)=>{for(var n in t||(t={}))kr.call(t,n)&&On(e,n,t[n]);if(Cn)for(var n of Cn(t))Fr.call(t,n)&&On(e,n,t[n]);return e},Be=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())}),Hr={"":3e3,srgb:3001};function Wr(e,t){parseInt(vt,10)>=152?e.colorSpace=t:e.encoding=Hr[t]}var zr=class{get pending(){return Promise.all(this._pendings)}constructor(e,t){this._parser=e,this._materialParams=t,this._pendings=[]}assignPrimitive(e,t){t!=null&&(this._materialParams[e]=t)}assignColor(e,t,n){if(t!=null){const i=new ne().fromArray(t);n&&i.convertSRGBToLinear(),this._materialParams[e]=i}}assignTexture(e,t,n){return Be(this,null,function*(){const i=Be(this,null,function*(){if(t!=null){const r=yield this._parser.assignTexture(this._materialParams,e,t);if(r==null){console.warn("GLTFMToonMaterialParamsAssignHelper: Failed to load texture. The rendering result may be wrong");return}n&&Wr(r,"srgb")}});return this._pendings.push(i),i})}assignTextureByIndex(e,t,n){return Be(this,null,function*(){return this.assignTexture(e,t!=null?{index:t}:void 0,n)})}},jr=`// #define PHONG

varying vec3 vViewPosition;

#ifndef FLAT_SHADED
  varying vec3 vNormal;
#endif

#include <common>

// #include <uv_pars_vertex>
#ifdef MTOON_USE_UV
  varying vec2 vUv;

  // COMPAT: pre-r151 uses a common uvTransform
  #if THREE_VRM_THREE_REVISION < 151
    uniform mat3 uvTransform;
  #endif
#endif

// #include <uv2_pars_vertex>
// COMAPT: pre-r151 uses uv2 for lightMap and aoMap
#if THREE_VRM_THREE_REVISION < 151
  #if defined( USE_LIGHTMAP ) || defined( USE_AOMAP )
    attribute vec2 uv2;
    varying vec2 vUv2;
    uniform mat3 uv2Transform;
  #endif
#endif

// #include <displacementmap_pars_vertex>
// #include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>

#ifdef USE_OUTLINEWIDTHMULTIPLYTEXTURE
  uniform sampler2D outlineWidthMultiplyTexture;
  uniform mat3 outlineWidthMultiplyTextureUvTransform;
#endif

uniform float outlineWidthFactor;

void main() {

  // #include <uv_vertex>
  #ifdef MTOON_USE_UV
    // COMPAT: pre-r151 uses a common uvTransform
    #if THREE_VRM_THREE_REVISION >= 151
      vUv = uv;
    #else
      vUv = ( uvTransform * vec3( uv, 1 ) ).xy;
    #endif
  #endif

  // #include <uv2_vertex>
  // COMAPT: pre-r151 uses uv2 for lightMap and aoMap
  #if THREE_VRM_THREE_REVISION < 151
    #if defined( USE_LIGHTMAP ) || defined( USE_AOMAP )
      vUv2 = ( uv2Transform * vec3( uv2, 1 ) ).xy;
    #endif
  #endif

  #include <color_vertex>

  #include <beginnormal_vertex>
  #include <morphnormal_vertex>
  #include <skinbase_vertex>
  #include <skinnormal_vertex>

  // we need this to compute the outline properly
  objectNormal = normalize( objectNormal );

  #include <defaultnormal_vertex>

  #ifndef FLAT_SHADED // Normal computed with derivatives when FLAT_SHADED
    vNormal = normalize( transformedNormal );
  #endif

  #include <begin_vertex>

  #include <morphtarget_vertex>
  #include <skinning_vertex>
  // #include <displacementmap_vertex>
  #include <project_vertex>
  #include <logdepthbuf_vertex>
  #include <clipping_planes_vertex>

  vViewPosition = - mvPosition.xyz;

  #ifdef OUTLINE
    float worldNormalLength = length( transformedNormal );
    vec3 outlineOffset = outlineWidthFactor * worldNormalLength * objectNormal;

    #ifdef USE_OUTLINEWIDTHMULTIPLYTEXTURE
      vec2 outlineWidthMultiplyTextureUv = ( outlineWidthMultiplyTextureUvTransform * vec3( vUv, 1 ) ).xy;
      float outlineTex = texture2D( outlineWidthMultiplyTexture, outlineWidthMultiplyTextureUv ).g;
      outlineOffset *= outlineTex;
    #endif

    #ifdef OUTLINE_WIDTH_SCREEN
      outlineOffset *= vViewPosition.z / projectionMatrix[ 1 ].y;
    #endif

    gl_Position = projectionMatrix * modelViewMatrix * vec4( outlineOffset + transformed, 1.0 );

    gl_Position.z += 1E-6 * gl_Position.w; // anti-artifact magic
  #endif

  #include <worldpos_vertex>
  // #include <envmap_vertex>
  #include <shadowmap_vertex>
  #include <fog_vertex>

}`,qr=`// #define PHONG

uniform vec3 litFactor;

uniform float opacity;

uniform vec3 shadeColorFactor;
#ifdef USE_SHADEMULTIPLYTEXTURE
  uniform sampler2D shadeMultiplyTexture;
  uniform mat3 shadeMultiplyTextureUvTransform;
#endif

uniform float shadingShiftFactor;
uniform float shadingToonyFactor;

#ifdef USE_SHADINGSHIFTTEXTURE
  uniform sampler2D shadingShiftTexture;
  uniform mat3 shadingShiftTextureUvTransform;
  uniform float shadingShiftTextureScale;
#endif

uniform float giEqualizationFactor;

uniform vec3 parametricRimColorFactor;
#ifdef USE_RIMMULTIPLYTEXTURE
  uniform sampler2D rimMultiplyTexture;
  uniform mat3 rimMultiplyTextureUvTransform;
#endif
uniform float rimLightingMixFactor;
uniform float parametricRimFresnelPowerFactor;
uniform float parametricRimLiftFactor;

#ifdef USE_MATCAPTEXTURE
  uniform vec3 matcapFactor;
  uniform sampler2D matcapTexture;
  uniform mat3 matcapTextureUvTransform;
#endif

uniform vec3 emissive;
uniform float emissiveIntensity;

uniform vec3 outlineColorFactor;
uniform float outlineLightingMixFactor;

#ifdef USE_UVANIMATIONMASKTEXTURE
  uniform sampler2D uvAnimationMaskTexture;
  uniform mat3 uvAnimationMaskTextureUvTransform;
#endif

uniform float uvAnimationScrollXOffset;
uniform float uvAnimationScrollYOffset;
uniform float uvAnimationRotationPhase;

#include <common>
#include <packing>
#include <dithering_pars_fragment>
#include <color_pars_fragment>

// #include <uv_pars_fragment>
#if ( defined( MTOON_USE_UV ) && !defined( MTOON_UVS_VERTEX_ONLY ) )
  varying vec2 vUv;
#endif

// #include <uv2_pars_fragment>
// COMAPT: pre-r151 uses uv2 for lightMap and aoMap
#if THREE_VRM_THREE_REVISION < 151
  #if defined( USE_LIGHTMAP ) || defined( USE_AOMAP )
    varying vec2 vUv2;
  #endif
#endif

#include <map_pars_fragment>

#ifdef USE_MAP
  uniform mat3 mapUvTransform;
#endif

// #include <alphamap_pars_fragment>

#include <alphatest_pars_fragment>

#include <aomap_pars_fragment>
// #include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>

#ifdef USE_EMISSIVEMAP
  uniform mat3 emissiveMapUvTransform;
#endif

// #include <envmap_common_pars_fragment>
// #include <envmap_pars_fragment>
// #include <cube_uv_reflection_fragment>
#include <fog_pars_fragment>

// #include <bsdfs>
// COMPAT: pre-r151 doesn't have BRDF_Lambert in <common>
#if THREE_VRM_THREE_REVISION < 151
  vec3 BRDF_Lambert( const in vec3 diffuseColor ) {
    return RECIPROCAL_PI * diffuseColor;
  }
#endif

#include <lights_pars_begin>

#include <normal_pars_fragment>

// #include <lights_phong_pars_fragment>
varying vec3 vViewPosition;

struct MToonMaterial {
  vec3 diffuseColor;
  vec3 shadeColor;
  float shadingShift;
};

float linearstep( float a, float b, float t ) {
  return clamp( ( t - a ) / ( b - a ), 0.0, 1.0 );
}

/**
 * Convert NdotL into toon shading factor using shadingShift and shadingToony
 */
float getShading(
  const in float dotNL,
  const in float shadow,
  const in float shadingShift
) {
  float shading = dotNL;
  shading = shading + shadingShift;
  shading = linearstep( -1.0 + shadingToonyFactor, 1.0 - shadingToonyFactor, shading );
  shading *= shadow;
  return shading;
}

/**
 * Mix diffuseColor and shadeColor using shading factor and light color
 */
vec3 getDiffuse(
  const in MToonMaterial material,
  const in float shading,
  in vec3 lightColor
) {
  #ifdef DEBUG_LITSHADERATE
    return vec3( BRDF_Lambert( shading * lightColor ) );
  #endif

  vec3 col = lightColor * BRDF_Lambert( mix( material.shadeColor, material.diffuseColor, shading ) );

  // The "comment out if you want to PBR absolutely" line
  #ifdef V0_COMPAT_SHADE
    col = min( col, material.diffuseColor );
  #endif

  return col;
}

// COMPAT: pre-r156 uses a struct GeometricContext
#if THREE_VRM_THREE_REVISION >= 157
  void RE_Direct_MToon( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in MToonMaterial material, const in float shadow, inout ReflectedLight reflectedLight ) {
    float dotNL = clamp( dot( geometryNormal, directLight.direction ), -1.0, 1.0 );
    vec3 irradiance = directLight.color;

    // directSpecular will be used for rim lighting, not an actual specular
    reflectedLight.directSpecular += irradiance;

    irradiance *= dotNL;

    float shading = getShading( dotNL, shadow, material.shadingShift );

    // toon shaded diffuse
    reflectedLight.directDiffuse += getDiffuse( material, shading, directLight.color );
  }

  void RE_IndirectDiffuse_MToon( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in MToonMaterial material, inout ReflectedLight reflectedLight ) {
    // indirect diffuse will use diffuseColor, no shadeColor involved
    reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );

    // directSpecular will be used for rim lighting, not an actual specular
    reflectedLight.directSpecular += irradiance;
  }
#else
  void RE_Direct_MToon( const in IncidentLight directLight, const in GeometricContext geometry, const in MToonMaterial material, const in float shadow, inout ReflectedLight reflectedLight ) {
    float dotNL = clamp( dot( geometry.normal, directLight.direction ), -1.0, 1.0 );
    vec3 irradiance = directLight.color;

    // directSpecular will be used for rim lighting, not an actual specular
    reflectedLight.directSpecular += irradiance;

    irradiance *= dotNL;

    float shading = getShading( dotNL, shadow, material.shadingShift );

    // toon shaded diffuse
    reflectedLight.directDiffuse += getDiffuse( material, shading, directLight.color );
  }

  void RE_IndirectDiffuse_MToon( const in vec3 irradiance, const in GeometricContext geometry, const in MToonMaterial material, inout ReflectedLight reflectedLight ) {
    // indirect diffuse will use diffuseColor, no shadeColor involved
    reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );

    // directSpecular will be used for rim lighting, not an actual specular
    reflectedLight.directSpecular += irradiance;
  }
#endif

#define RE_Direct RE_Direct_MToon
#define RE_IndirectDiffuse RE_IndirectDiffuse_MToon
#define Material_LightProbeLOD( material ) (0)

#include <shadowmap_pars_fragment>
// #include <bumpmap_pars_fragment>

// #include <normalmap_pars_fragment>
#ifdef USE_NORMALMAP

  uniform sampler2D normalMap;
  uniform mat3 normalMapUvTransform;
  uniform vec2 normalScale;

#endif

// COMPAT: pre-r151
// USE_NORMALMAP_OBJECTSPACE used to be OBJECTSPACE_NORMALMAP in pre-r151
#if defined( USE_NORMALMAP_OBJECTSPACE ) || defined( OBJECTSPACE_NORMALMAP )

  uniform mat3 normalMatrix;

#endif

// COMPAT: pre-r151
// USE_NORMALMAP_TANGENTSPACE used to be TANGENTSPACE_NORMALMAP in pre-r151
#if ! defined ( USE_TANGENT ) && ( defined ( USE_NORMALMAP_TANGENTSPACE ) || defined ( TANGENTSPACE_NORMALMAP ) )

  // Per-Pixel Tangent Space Normal Mapping
  // http://hacksoflife.blogspot.ch/2009/11/per-pixel-tangent-space-normal-mapping.html

  // three-vrm specific change: it requires \`uv\` as an input in order to support uv scrolls

  // Temporary compat against shader change @ Three.js r126, r151
  #if THREE_VRM_THREE_REVISION >= 151

    mat3 getTangentFrame( vec3 eye_pos, vec3 surf_norm, vec2 uv ) {

      vec3 q0 = dFdx( eye_pos.xyz );
      vec3 q1 = dFdy( eye_pos.xyz );
      vec2 st0 = dFdx( uv.st );
      vec2 st1 = dFdy( uv.st );

      vec3 N = surf_norm;

      vec3 q1perp = cross( q1, N );
      vec3 q0perp = cross( N, q0 );

      vec3 T = q1perp * st0.x + q0perp * st1.x;
      vec3 B = q1perp * st0.y + q0perp * st1.y;

      float det = max( dot( T, T ), dot( B, B ) );
      float scale = ( det == 0.0 ) ? 0.0 : inversesqrt( det );

      return mat3( T * scale, B * scale, N );

    }

  #else

    vec3 perturbNormal2Arb( vec2 uv, vec3 eye_pos, vec3 surf_norm, vec3 mapN, float faceDirection ) {

      vec3 q0 = vec3( dFdx( eye_pos.x ), dFdx( eye_pos.y ), dFdx( eye_pos.z ) );
      vec3 q1 = vec3( dFdy( eye_pos.x ), dFdy( eye_pos.y ), dFdy( eye_pos.z ) );
      vec2 st0 = dFdx( uv.st );
      vec2 st1 = dFdy( uv.st );

      vec3 N = normalize( surf_norm );

      vec3 q1perp = cross( q1, N );
      vec3 q0perp = cross( N, q0 );

      vec3 T = q1perp * st0.x + q0perp * st1.x;
      vec3 B = q1perp * st0.y + q0perp * st1.y;

      // three-vrm specific change: Workaround for the issue that happens when delta of uv = 0.0
      // TODO: Is this still required? Or shall I make a PR about it?
      if ( length( T ) == 0.0 || length( B ) == 0.0 ) {
        return surf_norm;
      }

      float det = max( dot( T, T ), dot( B, B ) );
      float scale = ( det == 0.0 ) ? 0.0 : faceDirection * inversesqrt( det );

      return normalize( T * ( mapN.x * scale ) + B * ( mapN.y * scale ) + N * mapN.z );

    }

  #endif

#endif

// #include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>

// == post correction ==========================================================
void postCorrection() {
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
  #include <fog_fragment>
  #include <premultiplied_alpha_fragment>
  #include <dithering_fragment>
}

// == main procedure ===========================================================
void main() {
  #include <clipping_planes_fragment>

  vec2 uv = vec2(0.5, 0.5);

  #if ( defined( MTOON_USE_UV ) && !defined( MTOON_UVS_VERTEX_ONLY ) )
    uv = vUv;

    float uvAnimMask = 1.0;
    #ifdef USE_UVANIMATIONMASKTEXTURE
      vec2 uvAnimationMaskTextureUv = ( uvAnimationMaskTextureUvTransform * vec3( uv, 1 ) ).xy;
      uvAnimMask = texture2D( uvAnimationMaskTexture, uvAnimationMaskTextureUv ).b;
    #endif

    float uvRotCos = cos( uvAnimationRotationPhase * uvAnimMask );
    float uvRotSin = sin( uvAnimationRotationPhase * uvAnimMask );
    uv = mat2( uvRotCos, -uvRotSin, uvRotSin, uvRotCos ) * ( uv - 0.5 ) + 0.5;
    uv = uv + vec2( uvAnimationScrollXOffset, uvAnimationScrollYOffset ) * uvAnimMask;
  #endif

  #ifdef DEBUG_UV
    gl_FragColor = vec4( 0.0, 0.0, 0.0, 1.0 );
    #if ( defined( MTOON_USE_UV ) && !defined( MTOON_UVS_VERTEX_ONLY ) )
      gl_FragColor = vec4( uv, 0.0, 1.0 );
    #endif
    return;
  #endif

  vec4 diffuseColor = vec4( litFactor, opacity );
  ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
  vec3 totalEmissiveRadiance = emissive * emissiveIntensity;

  #include <logdepthbuf_fragment>

  // #include <map_fragment>
  #ifdef USE_MAP
    vec2 mapUv = ( mapUvTransform * vec3( uv, 1 ) ).xy;
    vec4 sampledDiffuseColor = texture2D( map, mapUv );
    #ifdef DECODE_VIDEO_TEXTURE
      sampledDiffuseColor = vec4( mix( pow( sampledDiffuseColor.rgb * 0.9478672986 + vec3( 0.0521327014 ), vec3( 2.4 ) ), sampledDiffuseColor.rgb * 0.0773993808, vec3( lessThanEqual( sampledDiffuseColor.rgb, vec3( 0.04045 ) ) ) ), sampledDiffuseColor.w );
    #endif
    diffuseColor *= sampledDiffuseColor;
  #endif

  // #include <color_fragment>
  #if ( defined( USE_COLOR ) && !defined( IGNORE_VERTEX_COLOR ) )
    diffuseColor.rgb *= vColor;
  #endif

  // #include <alphamap_fragment>

  #include <alphatest_fragment>

  // #include <specularmap_fragment>

  // #include <normal_fragment_begin>
  float faceDirection = gl_FrontFacing ? 1.0 : -1.0;

  #ifdef FLAT_SHADED

    vec3 fdx = dFdx( vViewPosition );
    vec3 fdy = dFdy( vViewPosition );
    vec3 normal = normalize( cross( fdx, fdy ) );

  #else

    vec3 normal = normalize( vNormal );

    #ifdef DOUBLE_SIDED

      normal *= faceDirection;

    #endif

  #endif

  #ifdef USE_NORMALMAP

    vec2 normalMapUv = ( normalMapUvTransform * vec3( uv, 1 ) ).xy;

  #endif

  #ifdef USE_NORMALMAP_TANGENTSPACE

    #ifdef USE_TANGENT

      mat3 tbn = mat3( normalize( vTangent ), normalize( vBitangent ), normal );

    #else

      mat3 tbn = getTangentFrame( - vViewPosition, normal, normalMapUv );

    #endif

    #if defined( DOUBLE_SIDED ) && ! defined( FLAT_SHADED )

      tbn[0] *= faceDirection;
      tbn[1] *= faceDirection;

    #endif

  #endif

  #ifdef USE_CLEARCOAT_NORMALMAP

    #ifdef USE_TANGENT

      mat3 tbn2 = mat3( normalize( vTangent ), normalize( vBitangent ), normal );

    #else

      mat3 tbn2 = getTangentFrame( - vViewPosition, normal, vClearcoatNormalMapUv );

    #endif

    #if defined( DOUBLE_SIDED ) && ! defined( FLAT_SHADED )

      tbn2[0] *= faceDirection;
      tbn2[1] *= faceDirection;

    #endif

  #endif

  // non perturbed normal for clearcoat among others

  vec3 nonPerturbedNormal = normal;

  #ifdef OUTLINE
    normal *= -1.0;
  #endif

  // #include <normal_fragment_maps>

  // COMPAT: pre-r151
  // USE_NORMALMAP_OBJECTSPACE used to be OBJECTSPACE_NORMALMAP in pre-r151
  #if defined( USE_NORMALMAP_OBJECTSPACE ) || defined( OBJECTSPACE_NORMALMAP )

    normal = texture2D( normalMap, normalMapUv ).xyz * 2.0 - 1.0; // overrides both flatShading and attribute normals

    #ifdef FLIP_SIDED

      normal = - normal;

    #endif

    #ifdef DOUBLE_SIDED

      normal = normal * faceDirection;

    #endif

    normal = normalize( normalMatrix * normal );

  // COMPAT: pre-r151
  // USE_NORMALMAP_TANGENTSPACE used to be TANGENTSPACE_NORMALMAP in pre-r151
  #elif defined( USE_NORMALMAP_TANGENTSPACE ) || defined( TANGENTSPACE_NORMALMAP )

    vec3 mapN = texture2D( normalMap, normalMapUv ).xyz * 2.0 - 1.0;
    mapN.xy *= normalScale;

    // COMPAT: pre-r151
    #if THREE_VRM_THREE_REVISION >= 151 || defined( USE_TANGENT )

      normal = normalize( tbn * mapN );

    #else

      normal = perturbNormal2Arb( uv, -vViewPosition, normal, mapN, faceDirection );

    #endif

  #endif

  // #include <emissivemap_fragment>
  #ifdef USE_EMISSIVEMAP
    vec2 emissiveMapUv = ( emissiveMapUvTransform * vec3( uv, 1 ) ).xy;
    totalEmissiveRadiance *= texture2D( emissiveMap, emissiveMapUv ).rgb;
  #endif

  #ifdef DEBUG_NORMAL
    gl_FragColor = vec4( 0.5 + 0.5 * normal, 1.0 );
    return;
  #endif

  // -- MToon: lighting --------------------------------------------------------
  // accumulation
  // #include <lights_phong_fragment>
  MToonMaterial material;

  material.diffuseColor = diffuseColor.rgb;

  material.shadeColor = shadeColorFactor;
  #ifdef USE_SHADEMULTIPLYTEXTURE
    vec2 shadeMultiplyTextureUv = ( shadeMultiplyTextureUvTransform * vec3( uv, 1 ) ).xy;
    material.shadeColor *= texture2D( shadeMultiplyTexture, shadeMultiplyTextureUv ).rgb;
  #endif

  #if ( defined( USE_COLOR ) && !defined( IGNORE_VERTEX_COLOR ) )
    material.shadeColor.rgb *= vColor;
  #endif

  material.shadingShift = shadingShiftFactor;
  #ifdef USE_SHADINGSHIFTTEXTURE
    vec2 shadingShiftTextureUv = ( shadingShiftTextureUvTransform * vec3( uv, 1 ) ).xy;
    material.shadingShift += texture2D( shadingShiftTexture, shadingShiftTextureUv ).r * shadingShiftTextureScale;
  #endif

  // #include <lights_fragment_begin>

  // MToon Specific changes:
  // Since we want to take shadows into account of shading instead of irradiance,
  // we had to modify the codes that multiplies the results of shadowmap into color of direct lights.

  // COMPAT: pre-r156 uses a struct GeometricContext
  #if THREE_VRM_THREE_REVISION >= 157
    vec3 geometryPosition = - vViewPosition;
    vec3 geometryNormal = normal;
    vec3 geometryViewDir = ( isOrthographic ) ? vec3( 0, 0, 1 ) : normalize( vViewPosition );

    vec3 geometryClearcoatNormal;

    #ifdef USE_CLEARCOAT

      geometryClearcoatNormal = clearcoatNormal;

    #endif
  #else
    GeometricContext geometry;

    geometry.position = - vViewPosition;
    geometry.normal = normal;
    geometry.viewDir = ( isOrthographic ) ? vec3( 0, 0, 1 ) : normalize( vViewPosition );

    #ifdef USE_CLEARCOAT

      geometry.clearcoatNormal = clearcoatNormal;

    #endif
  #endif

  IncidentLight directLight;

  // since these variables will be used in unrolled loop, we have to define in prior
  float shadow;

  #if ( NUM_POINT_LIGHTS > 0 ) && defined( RE_Direct )

    PointLight pointLight;
    #if defined( USE_SHADOWMAP ) && NUM_POINT_LIGHT_SHADOWS > 0
    PointLightShadow pointLightShadow;
    #endif

    #pragma unroll_loop_start
    for ( int i = 0; i < NUM_POINT_LIGHTS; i ++ ) {

      pointLight = pointLights[ i ];

      // COMPAT: pre-r156 uses a struct GeometricContext
      #if THREE_VRM_THREE_REVISION >= 157
        getPointLightInfo( pointLight, geometryPosition, directLight );
      #else
        getPointLightInfo( pointLight, geometry, directLight );
      #endif

      shadow = 1.0;
      #if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_POINT_LIGHT_SHADOWS )
      pointLightShadow = pointLightShadows[ i ];
      // COMPAT: pre-r166
      // r166 introduced shadowIntensity
      #if THREE_VRM_THREE_REVISION >= 166
        shadow = all( bvec2( directLight.visible, receiveShadow ) ) ? getPointShadow( pointShadowMap[ i ], pointLightShadow.shadowMapSize, pointLightShadow.shadowIntensity, pointLightShadow.shadowBias, pointLightShadow.shadowRadius, vPointShadowCoord[ i ], pointLightShadow.shadowCameraNear, pointLightShadow.shadowCameraFar ) : 1.0;
      #else
        shadow = all( bvec2( directLight.visible, receiveShadow ) ) ? getPointShadow( pointShadowMap[ i ], pointLightShadow.shadowMapSize, pointLightShadow.shadowBias, pointLightShadow.shadowRadius, vPointShadowCoord[ i ], pointLightShadow.shadowCameraNear, pointLightShadow.shadowCameraFar ) : 1.0;
      #endif
      #endif

      // COMPAT: pre-r156 uses a struct GeometricContext
      #if THREE_VRM_THREE_REVISION >= 157
        RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, shadow, reflectedLight );
      #else
        RE_Direct( directLight, geometry, material, shadow, reflectedLight );
      #endif

    }
    #pragma unroll_loop_end

  #endif

  #if ( NUM_SPOT_LIGHTS > 0 ) && defined( RE_Direct )

    SpotLight spotLight;
    // COMPAT: pre-r144 uses NUM_SPOT_LIGHT_SHADOWS, r144+ uses NUM_SPOT_LIGHT_COORDS
    #if THREE_VRM_THREE_REVISION >= 144
      #if defined( USE_SHADOWMAP ) && NUM_SPOT_LIGHT_COORDS > 0
      SpotLightShadow spotLightShadow;
      #endif
    #elif defined( USE_SHADOWMAP ) && NUM_SPOT_LIGHT_SHADOWS > 0
    SpotLightShadow spotLightShadow;
    #endif

    #pragma unroll_loop_start
    for ( int i = 0; i < NUM_SPOT_LIGHTS; i ++ ) {

      spotLight = spotLights[ i ];

      // COMPAT: pre-r156 uses a struct GeometricContext
      #if THREE_VRM_THREE_REVISION >= 157
        getSpotLightInfo( spotLight, geometryPosition, directLight );
      #else
        getSpotLightInfo( spotLight, geometry, directLight );
      #endif

      shadow = 1.0;
      // COMPAT: pre-r144 uses NUM_SPOT_LIGHT_SHADOWS and vSpotShadowCoord, r144+ uses NUM_SPOT_LIGHT_COORDS and vSpotLightCoord
      // COMPAT: pre-r166 does not have shadowIntensity, r166+ has shadowIntensity
      #if THREE_VRM_THREE_REVISION >= 166
        #if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_COORDS )
        spotLightShadow = spotLightShadows[ i ];
        shadow = all( bvec2( directLight.visible, receiveShadow ) ) ? getShadow( spotShadowMap[ i ], spotLightShadow.shadowMapSize, spotLightShadow.shadowIntensity, spotLightShadow.shadowBias, spotLightShadow.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
        #endif
      #elif THREE_VRM_THREE_REVISION >= 144
        #if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_COORDS )
        spotLightShadow = spotLightShadows[ i ];
        shadow = all( bvec2( directLight.visible, receiveShadow ) ) ? getShadow( spotShadowMap[ i ], spotLightShadow.shadowMapSize, spotLightShadow.shadowBias, spotLightShadow.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
        #endif
      #elif defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
      spotLightShadow = spotLightShadows[ i ];
      shadow = all( bvec2( directLight.visible, receiveShadow ) ) ? getShadow( spotShadowMap[ i ], spotLightShadow.shadowMapSize, spotLightShadow.shadowBias, spotLightShadow.shadowRadius, vSpotShadowCoord[ i ] ) : 1.0;
      #endif

      // COMPAT: pre-r156 uses a struct GeometricContext
      #if THREE_VRM_THREE_REVISION >= 157
        RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, shadow, reflectedLight );
      #else
        RE_Direct( directLight, geometry, material, shadow, reflectedLight );
      #endif

    }
    #pragma unroll_loop_end

  #endif

  #if ( NUM_DIR_LIGHTS > 0 ) && defined( RE_Direct )

    DirectionalLight directionalLight;
    #if defined( USE_SHADOWMAP ) && NUM_DIR_LIGHT_SHADOWS > 0
    DirectionalLightShadow directionalLightShadow;
    #endif

    #pragma unroll_loop_start
    for ( int i = 0; i < NUM_DIR_LIGHTS; i ++ ) {

      directionalLight = directionalLights[ i ];

      // COMPAT: pre-r156 uses a struct GeometricContext
      #if THREE_VRM_THREE_REVISION >= 157
        getDirectionalLightInfo( directionalLight, directLight );
      #else
        getDirectionalLightInfo( directionalLight, geometry, directLight );
      #endif

      shadow = 1.0;
      #if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_DIR_LIGHT_SHADOWS )
      directionalLightShadow = directionalLightShadows[ i ];
      // COMPAT: pre-r166
      // r166 introduced shadowIntensity
      #if THREE_VRM_THREE_REVISION >= 166
        shadow = all( bvec2( directLight.visible, receiveShadow ) ) ? getShadow( directionalShadowMap[ i ], directionalLightShadow.shadowMapSize, directionalLightShadow.shadowIntensity, directionalLightShadow.shadowBias, directionalLightShadow.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
      #else
        shadow = all( bvec2( directLight.visible, receiveShadow ) ) ? getShadow( directionalShadowMap[ i ], directionalLightShadow.shadowMapSize, directionalLightShadow.shadowBias, directionalLightShadow.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
      #endif
      #endif

      // COMPAT: pre-r156 uses a struct GeometricContext
      #if THREE_VRM_THREE_REVISION >= 157
        RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, shadow, reflectedLight );
      #else
        RE_Direct( directLight, geometry, material, shadow, reflectedLight );
      #endif

    }
    #pragma unroll_loop_end

  #endif

  // #if ( NUM_RECT_AREA_LIGHTS > 0 ) && defined( RE_Direct_RectArea )

  //   RectAreaLight rectAreaLight;

  //   #pragma unroll_loop_start
  //   for ( int i = 0; i < NUM_RECT_AREA_LIGHTS; i ++ ) {

  //     rectAreaLight = rectAreaLights[ i ];
  //     RE_Direct_RectArea( rectAreaLight, geometry, material, reflectedLight );

  //   }
  //   #pragma unroll_loop_end

  // #endif

  #if defined( RE_IndirectDiffuse )

    vec3 iblIrradiance = vec3( 0.0 );

    vec3 irradiance = getAmbientLightIrradiance( ambientLightColor );

    // COMPAT: pre-r156 uses a struct GeometricContext
    // COMPAT: pre-r156 doesn't have a define USE_LIGHT_PROBES
    #if THREE_VRM_THREE_REVISION >= 157
      #if defined( USE_LIGHT_PROBES )
        irradiance += getLightProbeIrradiance( lightProbe, geometryNormal );
      #endif
    #else
      irradiance += getLightProbeIrradiance( lightProbe, geometry.normal );
    #endif

    #if ( NUM_HEMI_LIGHTS > 0 )

      #pragma unroll_loop_start
      for ( int i = 0; i < NUM_HEMI_LIGHTS; i ++ ) {

        // COMPAT: pre-r156 uses a struct GeometricContext
        #if THREE_VRM_THREE_REVISION >= 157
          irradiance += getHemisphereLightIrradiance( hemisphereLights[ i ], geometryNormal );
        #else
          irradiance += getHemisphereLightIrradiance( hemisphereLights[ i ], geometry.normal );
        #endif

      }
      #pragma unroll_loop_end

    #endif

  #endif

  // #if defined( RE_IndirectSpecular )

  //   vec3 radiance = vec3( 0.0 );
  //   vec3 clearcoatRadiance = vec3( 0.0 );

  // #endif

  #include <lights_fragment_maps>
  #include <lights_fragment_end>

  // modulation
  #include <aomap_fragment>

  vec3 col = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse;

  #ifdef DEBUG_LITSHADERATE
    gl_FragColor = vec4( col, diffuseColor.a );
    postCorrection();
    return;
  #endif

  // -- MToon: rim lighting -----------------------------------------
  vec3 viewDir = normalize( vViewPosition );

  #ifndef PHYSICALLY_CORRECT_LIGHTS
    reflectedLight.directSpecular /= PI;
  #endif
  vec3 rimMix = mix( vec3( 1.0 ), reflectedLight.directSpecular, rimLightingMixFactor );

  vec3 rim = parametricRimColorFactor * pow( saturate( 1.0 - dot( viewDir, normal ) + parametricRimLiftFactor ), parametricRimFresnelPowerFactor );

  #ifdef USE_MATCAPTEXTURE
    {
      vec3 x = normalize( vec3( viewDir.z, 0.0, -viewDir.x ) );
      vec3 y = cross( viewDir, x ); // guaranteed to be normalized
      vec2 sphereUv = 0.5 + 0.5 * vec2( dot( x, normal ), -dot( y, normal ) );
      sphereUv = ( matcapTextureUvTransform * vec3( sphereUv, 1 ) ).xy;
      vec3 matcap = texture2D( matcapTexture, sphereUv ).rgb;
      rim += matcapFactor * matcap;
    }
  #endif

  #ifdef USE_RIMMULTIPLYTEXTURE
    vec2 rimMultiplyTextureUv = ( rimMultiplyTextureUvTransform * vec3( uv, 1 ) ).xy;
    rim *= texture2D( rimMultiplyTexture, rimMultiplyTextureUv ).rgb;
  #endif

  col += rimMix * rim;

  // -- MToon: Emission --------------------------------------------------------
  col += totalEmissiveRadiance;

  // #include <envmap_fragment>

  // -- Almost done! -----------------------------------------------------------
  #if defined( OUTLINE )
    col = outlineColorFactor.rgb * mix( vec3( 1.0 ), col, outlineLightingMixFactor );
  #endif

  #ifdef OPAQUE
    diffuseColor.a = 1.0;
  #endif

  gl_FragColor = vec4( col, diffuseColor.a );
  postCorrection();
}
`,Xr={None:"none"},Nn={None:"none",ScreenCoordinates:"screenCoordinates"},Gr={3e3:"",3001:"srgb"};function It(e){return parseInt(vt,10)>=152?e.colorSpace:Gr[e.encoding]}var Yr=class extends Hi{constructor(e={}){var t;super({vertexShader:jr,fragmentShader:qr}),this.uvAnimationScrollXSpeedFactor=0,this.uvAnimationScrollYSpeedFactor=0,this.uvAnimationRotationSpeedFactor=0,this.fog=!0,this.normalMapType=Wi,this._ignoreVertexColor=!0,this._v0CompatShade=!1,this._debugMode=Xr.None,this._outlineWidthMode=Nn.None,this._isOutline=!1,e.transparentWithZWrite&&(e.depthWrite=!0),delete e.transparentWithZWrite,e.fog=!0,e.lights=!0,e.clipping=!0,this.uniforms=zi.merge([Ke.common,Ke.normalmap,Ke.emissivemap,Ke.fog,Ke.lights,{litFactor:{value:new ne(1,1,1)},mapUvTransform:{value:new de},colorAlpha:{value:1},normalMapUvTransform:{value:new de},shadeColorFactor:{value:new ne(0,0,0)},shadeMultiplyTexture:{value:null},shadeMultiplyTextureUvTransform:{value:new de},shadingShiftFactor:{value:0},shadingShiftTexture:{value:null},shadingShiftTextureUvTransform:{value:new de},shadingShiftTextureScale:{value:1},shadingToonyFactor:{value:.9},giEqualizationFactor:{value:.9},matcapFactor:{value:new ne(1,1,1)},matcapTexture:{value:null},matcapTextureUvTransform:{value:new de},parametricRimColorFactor:{value:new ne(0,0,0)},rimMultiplyTexture:{value:null},rimMultiplyTextureUvTransform:{value:new de},rimLightingMixFactor:{value:1},parametricRimFresnelPowerFactor:{value:5},parametricRimLiftFactor:{value:0},emissive:{value:new ne(0,0,0)},emissiveIntensity:{value:1},emissiveMapUvTransform:{value:new de},outlineWidthMultiplyTexture:{value:null},outlineWidthMultiplyTextureUvTransform:{value:new de},outlineWidthFactor:{value:0},outlineColorFactor:{value:new ne(0,0,0)},outlineLightingMixFactor:{value:1},uvAnimationMaskTexture:{value:null},uvAnimationMaskTextureUvTransform:{value:new de},uvAnimationScrollXOffset:{value:0},uvAnimationScrollYOffset:{value:0},uvAnimationRotationPhase:{value:0}},(t=e.uniforms)!=null?t:{}]),this.setValues(e),this._uploadUniformsWorkaround(),this.customProgramCacheKey=()=>[...Object.entries(this._generateDefines()).map(([n,i])=>`${n}:${i}`),this.matcapTexture?`matcapTextureColorSpace:${It(this.matcapTexture)}`:"",this.shadeMultiplyTexture?`shadeMultiplyTextureColorSpace:${It(this.shadeMultiplyTexture)}`:"",this.rimMultiplyTexture?`rimMultiplyTextureColorSpace:${It(this.rimMultiplyTexture)}`:""].join(","),this.onBeforeCompile=n=>{const i=parseInt(vt,10),r=Object.entries(Un(Un({},this._generateDefines()),this.defines)).filter(([o,s])=>!!s).map(([o,s])=>`#define ${o} ${s}`).join(`
`)+`
`;n.vertexShader=r+n.vertexShader,n.fragmentShader=r+n.fragmentShader,i<154&&(n.fragmentShader=n.fragmentShader.replace("#include <colorspace_fragment>","#include <encodings_fragment>"))}}get color(){return this.uniforms.litFactor.value}set color(e){this.uniforms.litFactor.value=e}get map(){return this.uniforms.map.value}set map(e){this.uniforms.map.value=e}get normalMap(){return this.uniforms.normalMap.value}set normalMap(e){this.uniforms.normalMap.value=e}get normalScale(){return this.uniforms.normalScale.value}set normalScale(e){this.uniforms.normalScale.value=e}get emissive(){return this.uniforms.emissive.value}set emissive(e){this.uniforms.emissive.value=e}get emissiveIntensity(){return this.uniforms.emissiveIntensity.value}set emissiveIntensity(e){this.uniforms.emissiveIntensity.value=e}get emissiveMap(){return this.uniforms.emissiveMap.value}set emissiveMap(e){this.uniforms.emissiveMap.value=e}get shadeColorFactor(){return this.uniforms.shadeColorFactor.value}set shadeColorFactor(e){this.uniforms.shadeColorFactor.value=e}get shadeMultiplyTexture(){return this.uniforms.shadeMultiplyTexture.value}set shadeMultiplyTexture(e){this.uniforms.shadeMultiplyTexture.value=e}get shadingShiftFactor(){return this.uniforms.shadingShiftFactor.value}set shadingShiftFactor(e){this.uniforms.shadingShiftFactor.value=e}get shadingShiftTexture(){return this.uniforms.shadingShiftTexture.value}set shadingShiftTexture(e){this.uniforms.shadingShiftTexture.value=e}get shadingShiftTextureScale(){return this.uniforms.shadingShiftTextureScale.value}set shadingShiftTextureScale(e){this.uniforms.shadingShiftTextureScale.value=e}get shadingToonyFactor(){return this.uniforms.shadingToonyFactor.value}set shadingToonyFactor(e){this.uniforms.shadingToonyFactor.value=e}get giEqualizationFactor(){return this.uniforms.giEqualizationFactor.value}set giEqualizationFactor(e){this.uniforms.giEqualizationFactor.value=e}get matcapFactor(){return this.uniforms.matcapFactor.value}set matcapFactor(e){this.uniforms.matcapFactor.value=e}get matcapTexture(){return this.uniforms.matcapTexture.value}set matcapTexture(e){this.uniforms.matcapTexture.value=e}get parametricRimColorFactor(){return this.uniforms.parametricRimColorFactor.value}set parametricRimColorFactor(e){this.uniforms.parametricRimColorFactor.value=e}get rimMultiplyTexture(){return this.uniforms.rimMultiplyTexture.value}set rimMultiplyTexture(e){this.uniforms.rimMultiplyTexture.value=e}get rimLightingMixFactor(){return this.uniforms.rimLightingMixFactor.value}set rimLightingMixFactor(e){this.uniforms.rimLightingMixFactor.value=e}get parametricRimFresnelPowerFactor(){return this.uniforms.parametricRimFresnelPowerFactor.value}set parametricRimFresnelPowerFactor(e){this.uniforms.parametricRimFresnelPowerFactor.value=e}get parametricRimLiftFactor(){return this.uniforms.parametricRimLiftFactor.value}set parametricRimLiftFactor(e){this.uniforms.parametricRimLiftFactor.value=e}get outlineWidthMultiplyTexture(){return this.uniforms.outlineWidthMultiplyTexture.value}set outlineWidthMultiplyTexture(e){this.uniforms.outlineWidthMultiplyTexture.value=e}get outlineWidthFactor(){return this.uniforms.outlineWidthFactor.value}set outlineWidthFactor(e){this.uniforms.outlineWidthFactor.value=e}get outlineColorFactor(){return this.uniforms.outlineColorFactor.value}set outlineColorFactor(e){this.uniforms.outlineColorFactor.value=e}get outlineLightingMixFactor(){return this.uniforms.outlineLightingMixFactor.value}set outlineLightingMixFactor(e){this.uniforms.outlineLightingMixFactor.value=e}get uvAnimationMaskTexture(){return this.uniforms.uvAnimationMaskTexture.value}set uvAnimationMaskTexture(e){this.uniforms.uvAnimationMaskTexture.value=e}get uvAnimationScrollXOffset(){return this.uniforms.uvAnimationScrollXOffset.value}set uvAnimationScrollXOffset(e){this.uniforms.uvAnimationScrollXOffset.value=e}get uvAnimationScrollYOffset(){return this.uniforms.uvAnimationScrollYOffset.value}set uvAnimationScrollYOffset(e){this.uniforms.uvAnimationScrollYOffset.value=e}get uvAnimationRotationPhase(){return this.uniforms.uvAnimationRotationPhase.value}set uvAnimationRotationPhase(e){this.uniforms.uvAnimationRotationPhase.value=e}get ignoreVertexColor(){return this._ignoreVertexColor}set ignoreVertexColor(e){this._ignoreVertexColor=e,this.needsUpdate=!0}get v0CompatShade(){return this._v0CompatShade}set v0CompatShade(e){this._v0CompatShade=e,this.needsUpdate=!0}get debugMode(){return this._debugMode}set debugMode(e){this._debugMode=e,this.needsUpdate=!0}get outlineWidthMode(){return this._outlineWidthMode}set outlineWidthMode(e){this._outlineWidthMode=e,this.needsUpdate=!0}get isOutline(){return this._isOutline}set isOutline(e){this._isOutline=e,this.needsUpdate=!0}get isMToonMaterial(){return!0}update(e){this._uploadUniformsWorkaround(),this._updateUVAnimation(e)}copy(e){return super.copy(e),this.map=e.map,this.normalMap=e.normalMap,this.emissiveMap=e.emissiveMap,this.shadeMultiplyTexture=e.shadeMultiplyTexture,this.shadingShiftTexture=e.shadingShiftTexture,this.matcapTexture=e.matcapTexture,this.rimMultiplyTexture=e.rimMultiplyTexture,this.outlineWidthMultiplyTexture=e.outlineWidthMultiplyTexture,this.uvAnimationMaskTexture=e.uvAnimationMaskTexture,this.normalMapType=e.normalMapType,this.uvAnimationScrollXSpeedFactor=e.uvAnimationScrollXSpeedFactor,this.uvAnimationScrollYSpeedFactor=e.uvAnimationScrollYSpeedFactor,this.uvAnimationRotationSpeedFactor=e.uvAnimationRotationSpeedFactor,this.ignoreVertexColor=e.ignoreVertexColor,this.v0CompatShade=e.v0CompatShade,this.debugMode=e.debugMode,this.outlineWidthMode=e.outlineWidthMode,this.isOutline=e.isOutline,this.needsUpdate=!0,this}_updateUVAnimation(e){this.uniforms.uvAnimationScrollXOffset.value+=e*this.uvAnimationScrollXSpeedFactor,this.uniforms.uvAnimationScrollYOffset.value+=e*this.uvAnimationScrollYSpeedFactor,this.uniforms.uvAnimationRotationPhase.value+=e*this.uvAnimationRotationSpeedFactor,this.uniforms.alphaTest.value=this.alphaTest,this.uniformsNeedUpdate=!0}_uploadUniformsWorkaround(){this.uniforms.opacity.value=this.opacity,this._updateTextureMatrix(this.uniforms.map,this.uniforms.mapUvTransform),this._updateTextureMatrix(this.uniforms.normalMap,this.uniforms.normalMapUvTransform),this._updateTextureMatrix(this.uniforms.emissiveMap,this.uniforms.emissiveMapUvTransform),this._updateTextureMatrix(this.uniforms.shadeMultiplyTexture,this.uniforms.shadeMultiplyTextureUvTransform),this._updateTextureMatrix(this.uniforms.shadingShiftTexture,this.uniforms.shadingShiftTextureUvTransform),this._updateTextureMatrix(this.uniforms.matcapTexture,this.uniforms.matcapTextureUvTransform),this._updateTextureMatrix(this.uniforms.rimMultiplyTexture,this.uniforms.rimMultiplyTextureUvTransform),this._updateTextureMatrix(this.uniforms.outlineWidthMultiplyTexture,this.uniforms.outlineWidthMultiplyTextureUvTransform),this._updateTextureMatrix(this.uniforms.uvAnimationMaskTexture,this.uniforms.uvAnimationMaskTextureUvTransform),this.uniformsNeedUpdate=!0}_generateDefines(){const e=parseInt(vt,10),t=this.outlineWidthMultiplyTexture!==null,n=this.map!==null||this.normalMap!==null||this.emissiveMap!==null||this.shadeMultiplyTexture!==null||this.shadingShiftTexture!==null||this.rimMultiplyTexture!==null||this.uvAnimationMaskTexture!==null;return{THREE_VRM_THREE_REVISION:e,OUTLINE:this._isOutline,MTOON_USE_UV:t||n,MTOON_UVS_VERTEX_ONLY:t&&!n,V0_COMPAT_SHADE:this._v0CompatShade,USE_SHADEMULTIPLYTEXTURE:this.shadeMultiplyTexture!==null,USE_SHADINGSHIFTTEXTURE:this.shadingShiftTexture!==null,USE_MATCAPTEXTURE:this.matcapTexture!==null,USE_RIMMULTIPLYTEXTURE:this.rimMultiplyTexture!==null,USE_OUTLINEWIDTHMULTIPLYTEXTURE:this._isOutline&&this.outlineWidthMultiplyTexture!==null,USE_UVANIMATIONMASKTEXTURE:this.uvAnimationMaskTexture!==null,IGNORE_VERTEX_COLOR:this._ignoreVertexColor===!0,DEBUG_NORMAL:this._debugMode==="normal",DEBUG_LITSHADERATE:this._debugMode==="litShadeRate",DEBUG_UV:this._debugMode==="uv",OUTLINE_WIDTH_SCREEN:this._isOutline&&this._outlineWidthMode===Nn.ScreenCoordinates}}_updateTextureMatrix(e,t){e.value&&(e.value.matrixAutoUpdate&&e.value.updateMatrix(),t.value.copy(e.value.matrix))}},Qr=new Set(["1.0","1.0-beta"]),mi=class _t{get name(){return _t.EXTENSION_NAME}constructor(t,n={}){var i,r,o,s;this.parser=t,this.materialType=(i=n.materialType)!=null?i:Yr,this.renderOrderOffset=(r=n.renderOrderOffset)!=null?r:0,this.v0CompatShade=(o=n.v0CompatShade)!=null?o:!1,this.debugMode=(s=n.debugMode)!=null?s:"none",this._mToonMaterialSet=new Set}beforeRoot(){return Be(this,null,function*(){this._removeUnlitExtensionIfMToonExists()})}afterRoot(t){return Be(this,null,function*(){t.userData.vrmMToonMaterials=Array.from(this._mToonMaterialSet)})}getMaterialType(t){return this._getMToonExtension(t)?this.materialType:null}extendMaterialParams(t,n){const i=this._getMToonExtension(t);return i?this._extendMaterialParams(i,n):null}loadMesh(t){return Be(this,null,function*(){var n;const i=this.parser,o=(n=i.json.meshes)==null?void 0:n[t];if(o==null)throw new Error(`MToonMaterialLoaderPlugin: Attempt to use meshes[${t}] of glTF but the mesh doesn't exist`);const s=o.primitives,l=yield i.loadMesh(t);if(s.length===1){const a=l,u=s[0].material;u!=null&&this._setupPrimitive(a,u)}else{const a=l;for(let u=0;u<s.length;u++){const d=a.children[u],c=s[u].material;c!=null&&this._setupPrimitive(d,c)}}return l})}_removeUnlitExtensionIfMToonExists(){const i=this.parser.json.materials;i?.map((r,o)=>{var s;this._getMToonExtension(o)&&((s=r.extensions)!=null&&s.KHR_materials_unlit)&&delete r.extensions.KHR_materials_unlit})}_getMToonExtension(t){var n,i;const s=(n=this.parser.json.materials)==null?void 0:n[t];if(s==null){console.warn(`MToonMaterialLoaderPlugin: Attempt to use materials[${t}] of glTF but the material doesn't exist`);return}const l=(i=s.extensions)==null?void 0:i[_t.EXTENSION_NAME];if(l==null)return;const a=l.specVersion;if(!Qr.has(a)){console.warn(`MToonMaterialLoaderPlugin: Unknown ${_t.EXTENSION_NAME} specVersion "${a}"`);return}return l}_extendMaterialParams(t,n){return Be(this,null,function*(){var i;delete n.metalness,delete n.roughness;const r=new zr(this.parser,n);r.assignPrimitive("transparentWithZWrite",t.transparentWithZWrite),r.assignColor("shadeColorFactor",t.shadeColorFactor),r.assignTexture("shadeMultiplyTexture",t.shadeMultiplyTexture,!0),r.assignPrimitive("shadingShiftFactor",t.shadingShiftFactor),r.assignTexture("shadingShiftTexture",t.shadingShiftTexture,!0),r.assignPrimitive("shadingShiftTextureScale",(i=t.shadingShiftTexture)==null?void 0:i.scale),r.assignPrimitive("shadingToonyFactor",t.shadingToonyFactor),r.assignPrimitive("giEqualizationFactor",t.giEqualizationFactor),r.assignColor("matcapFactor",t.matcapFactor),r.assignTexture("matcapTexture",t.matcapTexture,!0),r.assignColor("parametricRimColorFactor",t.parametricRimColorFactor),r.assignTexture("rimMultiplyTexture",t.rimMultiplyTexture,!0),r.assignPrimitive("rimLightingMixFactor",t.rimLightingMixFactor),r.assignPrimitive("parametricRimFresnelPowerFactor",t.parametricRimFresnelPowerFactor),r.assignPrimitive("parametricRimLiftFactor",t.parametricRimLiftFactor),r.assignPrimitive("outlineWidthMode",t.outlineWidthMode),r.assignPrimitive("outlineWidthFactor",t.outlineWidthFactor),r.assignTexture("outlineWidthMultiplyTexture",t.outlineWidthMultiplyTexture,!1),r.assignColor("outlineColorFactor",t.outlineColorFactor),r.assignPrimitive("outlineLightingMixFactor",t.outlineLightingMixFactor),r.assignTexture("uvAnimationMaskTexture",t.uvAnimationMaskTexture,!1),r.assignPrimitive("uvAnimationScrollXSpeedFactor",t.uvAnimationScrollXSpeedFactor),r.assignPrimitive("uvAnimationScrollYSpeedFactor",t.uvAnimationScrollYSpeedFactor),r.assignPrimitive("uvAnimationRotationSpeedFactor",t.uvAnimationRotationSpeedFactor),r.assignPrimitive("v0CompatShade",this.v0CompatShade),r.assignPrimitive("debugMode",this.debugMode),yield r.pending})}_setupPrimitive(t,n){const i=this._getMToonExtension(n);if(i){const r=this._parseRenderOrder(i);t.renderOrder=r+this.renderOrderOffset,this._generateOutline(t),this._addToMaterialSet(t);return}}_shouldGenerateOutline(t){return typeof t.outlineWidthMode=="string"&&t.outlineWidthMode!=="none"&&typeof t.outlineWidthFactor=="number"&&t.outlineWidthFactor>0}_generateOutline(t){const n=t.material;if(!(n instanceof Di)||!this._shouldGenerateOutline(n))return;t.material=[n];const i=n.clone();i.name+=" (Outline)",i.isOutline=!0,i.side=ki,t.material.push(i);const r=t.geometry,o=r.index?r.index.count:r.attributes.position.count/3;r.addGroup(0,o,0),r.addGroup(0,o,1)}_addToMaterialSet(t){const n=t.material,i=new Set;Array.isArray(n)?n.forEach(r=>i.add(r)):i.add(n);for(const r of i)this._mToonMaterialSet.add(r)}_parseRenderOrder(t){var n;return(t.transparentWithZWrite?0:19)+((n=t.renderQueueOffsetNumber)!=null?n:0)}};mi.EXTENSION_NAME="VRMC_materials_mtoon";var $r=mi,Zr=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())}),gi=class qt{get name(){return qt.EXTENSION_NAME}constructor(t){this.parser=t}extendMaterialParams(t,n){return Zr(this,null,function*(){const i=this._getHDREmissiveMultiplierExtension(t);if(i==null)return;console.warn("VRMMaterialsHDREmissiveMultiplierLoaderPlugin: `VRMC_materials_hdr_emissiveMultiplier` is archived. Use `KHR_materials_emissive_strength` instead.");const r=i.emissiveMultiplier;n.emissiveIntensity=r})}_getHDREmissiveMultiplierExtension(t){var n,i;const s=(n=this.parser.json.materials)==null?void 0:n[t];if(s==null){console.warn(`VRMMaterialsHDREmissiveMultiplierLoaderPlugin: Attempt to use materials[${t}] of glTF but the material doesn't exist`);return}const l=(i=s.extensions)==null?void 0:i[qt.EXTENSION_NAME];if(l!=null)return l}};gi.EXTENSION_NAME="VRMC_materials_hdr_emissiveMultiplier";var Jr=gi,Kr=Object.defineProperty,eo=Object.defineProperties,to=Object.getOwnPropertyDescriptors,Vn=Object.getOwnPropertySymbols,no=Object.prototype.hasOwnProperty,io=Object.prototype.propertyIsEnumerable,Bn=(e,t,n)=>t in e?Kr(e,t,{enumerable:!0,configurable:!0,writable:!0,value:n}):e[t]=n,le=(e,t)=>{for(var n in t||(t={}))no.call(t,n)&&Bn(e,n,t[n]);if(Vn)for(var n of Vn(t))io.call(t,n)&&Bn(e,n,t[n]);return e},Dn=(e,t)=>eo(e,to(t)),ro=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())});function He(e){return Math.pow(e,2.2)}var oo=class{get name(){return"VRMMaterialsV0CompatPlugin"}constructor(e){var t;this.parser=e,this._renderQueueMapTransparent=new Map,this._renderQueueMapTransparentZWrite=new Map;const n=this.parser.json;n.extensionsUsed=(t=n.extensionsUsed)!=null?t:[],n.extensionsUsed.indexOf("KHR_texture_transform")===-1&&n.extensionsUsed.push("KHR_texture_transform")}beforeRoot(){return ro(this,null,function*(){var e;const t=this.parser.json,n=(e=t.extensions)==null?void 0:e.VRM,i=n?.materialProperties;i&&(this._populateRenderQueueMap(i),i.forEach((r,o)=>{var s,l;const a=(s=t.materials)==null?void 0:s[o];if(a==null){console.warn(`VRMMaterialsV0CompatPlugin: Attempt to use materials[${o}] of glTF but the material doesn't exist`);return}if(r.shader==="VRM/MToon"){const u=this._parseV0MToonProperties(r,a);t.materials[o]=u}else if((l=r.shader)!=null&&l.startsWith("VRM/Unlit")){const u=this._parseV0UnlitProperties(r,a);t.materials[o]=u}else r.shader==="VRM_USE_GLTFSHADER"||console.warn(`VRMMaterialsV0CompatPlugin: Unknown shader: ${r.shader}`)}))})}_parseV0MToonProperties(e,t){var n,i,r,o,s,l,a,u,d,c,h,p,f,m,_,g,M,y,x,R,T,S,P,U,L,N,F,Z,Y,Me,J,Q,K,ie,H,D,Ge,Ye,Te,re,ee,pe,Se,W,z,De,fe,me,xe,Ae,ge,Ee,Pe,Le,oe;const we=(i=(n=e.keywordMap)==null?void 0:n._ALPHABLEND_ON)!=null?i:!1,lt=((r=e.floatProperties)==null?void 0:r._ZWrite)===1&&we,Qe=this._v0ParseRenderQueue(e),w=(s=(o=e.keywordMap)==null?void 0:o._ALPHATEST_ON)!=null?s:!1,b=we?"BLEND":w?"MASK":"OPAQUE",E=w?(a=(l=e.floatProperties)==null?void 0:l._Cutoff)!=null?a:.5:void 0,C=((d=(u=e.floatProperties)==null?void 0:u._CullMode)!=null?d:2)===0,k=this._portTextureTransform(e),q=((h=(c=e.vectorProperties)==null?void 0:c._Color)!=null?h:[1,1,1,1]).map((nn,Bi)=>Bi===3?nn:He(nn)),G=(p=e.textureProperties)==null?void 0:p._MainTex,$=G!=null?{index:G,extensions:le({},k)}:void 0,se=(m=(f=e.floatProperties)==null?void 0:f._BumpScale)!=null?m:1,j=(_=e.textureProperties)==null?void 0:_._BumpMap,_e=j!=null?{index:j,scale:se,extensions:le({},k)}:void 0,be=((M=(g=e.vectorProperties)==null?void 0:g._EmissionColor)!=null?M:[0,0,0,1]).map(He),Ie=(y=e.textureProperties)==null?void 0:y._EmissionMap,$e=Ie!=null?{index:Ie,extensions:le({},k)}:void 0,Ze=((R=(x=e.vectorProperties)==null?void 0:x._ShadeColor)!=null?R:[.97,.81,.86,1]).map(He),Ce=(T=e.textureProperties)==null?void 0:T._ShadeTexture,Tt=Ce!=null?{index:Ce,extensions:le({},k)}:void 0;let ye=(P=(S=e.floatProperties)==null?void 0:S._ShadeShift)!=null?P:0,Oe=(L=(U=e.floatProperties)==null?void 0:U._ShadeToony)!=null?L:.9;Oe=V.lerp(Oe,1,.5+.5*ye),ye=-ye-(1-Oe);const ut=(F=(N=e.floatProperties)==null?void 0:N._IndirectLightIntensity)!=null?F:.1,St=ut?1-ut:void 0,Je=(Z=e.textureProperties)==null?void 0:Z._SphereAdd,O=Je!=null?[1,1,1]:void 0,Ri=Je!=null?{index:Je}:void 0,Ti=(Me=(Y=e.floatProperties)==null?void 0:Y._RimLightingMix)!=null?Me:0,Kt=(J=e.textureProperties)==null?void 0:J._RimTexture,Si=Kt!=null?{index:Kt,extensions:le({},k)}:void 0,Ai=((K=(Q=e.vectorProperties)==null?void 0:Q._RimColor)!=null?K:[0,0,0,1]).map(He),Ei=(H=(ie=e.floatProperties)==null?void 0:ie._RimFresnelPower)!=null?H:1,Pi=(Ge=(D=e.floatProperties)==null?void 0:D._RimLift)!=null?Ge:0,Li=["none","worldCoordinates","screenCoordinates"][(Te=(Ye=e.floatProperties)==null?void 0:Ye._OutlineWidthMode)!=null?Te:0];let At=(ee=(re=e.floatProperties)==null?void 0:re._OutlineWidth)!=null?ee:0;At=.01*At;const en=(pe=e.textureProperties)==null?void 0:pe._OutlineWidthTexture,bi=en!=null?{index:en,extensions:le({},k)}:void 0,Ii=((W=(Se=e.vectorProperties)==null?void 0:Se._OutlineColor)!=null?W:[0,0,0]).map(He),Ci=((De=(z=e.floatProperties)==null?void 0:z._OutlineColorMode)!=null?De:0)===1?(me=(fe=e.floatProperties)==null?void 0:fe._OutlineLightingMix)!=null?me:1:0,tn=(xe=e.textureProperties)==null?void 0:xe._UvAnimMaskTexture,Oi=tn!=null?{index:tn,extensions:le({},k)}:void 0,Ui=(ge=(Ae=e.floatProperties)==null?void 0:Ae._UvAnimScrollX)!=null?ge:0;let dt=(Pe=(Ee=e.floatProperties)==null?void 0:Ee._UvAnimScrollY)!=null?Pe:0;dt!=null&&(dt=-dt);const Ni=(oe=(Le=e.floatProperties)==null?void 0:Le._UvAnimRotation)!=null?oe:0,Vi={specVersion:"1.0",transparentWithZWrite:lt,renderQueueOffsetNumber:Qe,shadeColorFactor:Ze,shadeMultiplyTexture:Tt,shadingShiftFactor:ye,shadingToonyFactor:Oe,giEqualizationFactor:St,matcapFactor:O,matcapTexture:Ri,rimLightingMixFactor:Ti,rimMultiplyTexture:Si,parametricRimColorFactor:Ai,parametricRimFresnelPowerFactor:Ei,parametricRimLiftFactor:Pi,outlineWidthMode:Li,outlineWidthFactor:At,outlineWidthMultiplyTexture:bi,outlineColorFactor:Ii,outlineLightingMixFactor:Ci,uvAnimationMaskTexture:Oi,uvAnimationScrollXSpeedFactor:Ui,uvAnimationScrollYSpeedFactor:dt,uvAnimationRotationSpeedFactor:Ni};return Dn(le({},t),{pbrMetallicRoughness:{baseColorFactor:q,baseColorTexture:$},normalTexture:_e,emissiveTexture:$e,emissiveFactor:be,alphaMode:b,alphaCutoff:E,doubleSided:C,extensions:{VRMC_materials_mtoon:Vi}})}_parseV0UnlitProperties(e,t){var n,i,r,o,s;const l=e.shader==="VRM/UnlitTransparentZWrite",a=e.shader==="VRM/UnlitTransparent"||l,u=this._v0ParseRenderQueue(e),d=e.shader==="VRM/UnlitCutout",c=a?"BLEND":d?"MASK":"OPAQUE",h=d?(i=(n=e.floatProperties)==null?void 0:n._Cutoff)!=null?i:.5:void 0,p=this._portTextureTransform(e),f=((o=(r=e.vectorProperties)==null?void 0:r._Color)!=null?o:[1,1,1,1]).map(He),m=(s=e.textureProperties)==null?void 0:s._MainTex,_=m!=null?{index:m,extensions:le({},p)}:void 0,g={specVersion:"1.0",transparentWithZWrite:l,renderQueueOffsetNumber:u,shadeColorFactor:f,shadeMultiplyTexture:_};return Dn(le({},t),{pbrMetallicRoughness:{baseColorFactor:f,baseColorTexture:_},alphaMode:c,alphaCutoff:h,extensions:{VRMC_materials_mtoon:g}})}_portTextureTransform(e){var t,n,i,r,o;const s=(t=e.vectorProperties)==null?void 0:t._MainTex;if(s==null)return{};const l=[(n=s?.[0])!=null?n:0,(i=s?.[1])!=null?i:0],a=[(r=s?.[2])!=null?r:1,(o=s?.[3])!=null?o:1];return l[1]=1-a[1]-l[1],{KHR_texture_transform:{offset:l,scale:a}}}_v0ParseRenderQueue(e){var t,n;const i=e.shader==="VRM/UnlitTransparentZWrite",r=((t=e.keywordMap)==null?void 0:t._ALPHABLEND_ON)!=null||e.shader==="VRM/UnlitTransparent"||i,o=((n=e.floatProperties)==null?void 0:n._ZWrite)===1||i;let s=0;if(r){const l=e.renderQueue;l!=null&&(o?s=this._renderQueueMapTransparentZWrite.get(l):s=this._renderQueueMapTransparent.get(l))}return s}_populateRenderQueueMap(e){const t=new Set,n=new Set;e.forEach(i=>{var r,o;const s=i.shader==="VRM/UnlitTransparentZWrite",l=((r=i.keywordMap)==null?void 0:r._ALPHABLEND_ON)!=null||i.shader==="VRM/UnlitTransparent"||s,a=((o=i.floatProperties)==null?void 0:o._ZWrite)===1||s;if(l){const u=i.renderQueue;u!=null&&(a?n.add(u):t.add(u))}}),t.size>10&&console.warn(`VRMMaterialsV0CompatPlugin: This VRM uses ${t.size} render queues for Transparent materials while VRM 1.0 only supports up to 10 render queues. The model might not be rendered correctly.`),n.size>10&&console.warn(`VRMMaterialsV0CompatPlugin: This VRM uses ${n.size} render queues for TransparentZWrite materials while VRM 1.0 only supports up to 10 render queues. The model might not be rendered correctly.`),Array.from(t).sort().forEach((i,r)=>{const o=Math.min(Math.max(r-t.size+1,-9),0);this._renderQueueMapTransparent.set(i,o)}),Array.from(n).sort().forEach((i,r)=>{const o=Math.min(Math.max(r,0),9);this._renderQueueMapTransparentZWrite.set(i,o)})}},kn=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())}),Re=new v,Ct=class extends Xe{constructor(e){super(),this._attrPosition=new X(new Float32Array([0,0,0,0,0,0]),3),this._attrPosition.setUsage(ji);const t=new ve;t.setAttribute("position",this._attrPosition);const n=new Rt({color:16711935,depthTest:!1,depthWrite:!1});this._line=new qi(t,n),this.add(this._line),this.constraint=e}updateMatrixWorld(e){Re.setFromMatrixPosition(this.constraint.destination.matrixWorld),this._attrPosition.setXYZ(0,Re.x,Re.y,Re.z),this.constraint.source&&Re.setFromMatrixPosition(this.constraint.source.matrixWorld),this._attrPosition.setXYZ(1,Re.x,Re.y,Re.z),this._attrPosition.needsUpdate=!0,super.updateMatrixWorld(e)}};function Fn(e,t){return t.set(e.elements[12],e.elements[13],e.elements[14])}var so=new v,ao=new v;function lo(e,t){return e.decompose(so,t,ao),t}function xt(e){return e.invert?e.invert():e.inverse(),e}var Zt=class{constructor(e,t){this.destination=e,this.source=t,this.weight=1}},uo=new v,co=new v,ho=new v,po=new A,fo=new A,mo=new A,go=class extends Zt{get aimAxis(){return this._aimAxis}set aimAxis(e){this._aimAxis=e,this._v3AimAxis.set(e==="PositiveX"?1:e==="NegativeX"?-1:0,e==="PositiveY"?1:e==="NegativeY"?-1:0,e==="PositiveZ"?1:e==="NegativeZ"?-1:0)}get dependencies(){const e=new Set([this.source]);return this.destination.parent&&e.add(this.destination.parent),e}constructor(e,t){super(e,t),this._aimAxis="PositiveX",this._v3AimAxis=new v(1,0,0),this._dstRestQuat=new A}setInitState(){this._dstRestQuat.copy(this.destination.quaternion)}update(){this.destination.updateWorldMatrix(!0,!1),this.source.updateWorldMatrix(!0,!1);const e=po.identity(),t=fo.identity();this.destination.parent&&(lo(this.destination.parent.matrixWorld,e),xt(t.copy(e)));const n=uo.copy(this._v3AimAxis).applyQuaternion(this._dstRestQuat).applyQuaternion(e),i=Fn(this.source.matrixWorld,co).sub(Fn(this.destination.matrixWorld,ho)).normalize(),r=mo.setFromUnitVectors(n,i).premultiply(t).multiply(e).multiply(this._dstRestQuat);this.destination.quaternion.copy(this._dstRestQuat).slerp(r,this.weight)}};function _o(e,t){const n=[e];let i=e.parent;for(;i!==null;)n.unshift(i),i=i.parent;n.forEach(r=>{t(r)})}var vo=class{constructor(){this._constraints=new Set,this._objectConstraintsMap=new Map}get constraints(){return this._constraints}addConstraint(e){this._constraints.add(e);let t=this._objectConstraintsMap.get(e.destination);t==null&&(t=new Set,this._objectConstraintsMap.set(e.destination,t)),t.add(e)}deleteConstraint(e){this._constraints.delete(e),this._objectConstraintsMap.get(e.destination).delete(e)}setInitState(){const e=new Set,t=new Set;for(const n of this._constraints)this._processConstraint(n,e,t,i=>i.setInitState())}update(){const e=new Set,t=new Set;for(const n of this._constraints)this._processConstraint(n,e,t,i=>i.update())}_processConstraint(e,t,n,i){if(n.has(e))return;if(t.has(e))throw new Error("VRMNodeConstraintManager: Circular dependency detected while updating constraints");t.add(e);const r=e.dependencies;for(const o of r)_o(o,s=>{const l=this._objectConstraintsMap.get(s);if(l)for(const a of l)this._processConstraint(a,t,n,i)});i(e),n.add(e)}},Mo=new A,xo=new A,wo=class extends Zt{get dependencies(){return new Set([this.source])}constructor(e,t){super(e,t),this._dstRestQuat=new A,this._invSrcRestQuat=new A}setInitState(){this._dstRestQuat.copy(this.destination.quaternion),xt(this._invSrcRestQuat.copy(this.source.quaternion))}update(){const e=Mo.copy(this._invSrcRestQuat).multiply(this.source.quaternion),t=xo.copy(this._dstRestQuat).multiply(e);this.destination.quaternion.copy(this._dstRestQuat).slerp(t,this.weight)}},yo=new v,Ro=new A,To=new A,So=class extends Zt{get rollAxis(){return this._rollAxis}set rollAxis(e){this._rollAxis=e,this._v3RollAxis.set(e==="X"?1:0,e==="Y"?1:0,e==="Z"?1:0)}get dependencies(){return new Set([this.source])}constructor(e,t){super(e,t),this._rollAxis="X",this._v3RollAxis=new v(1,0,0),this._dstRestQuat=new A,this._invDstRestQuat=new A,this._invSrcRestQuatMulDstRestQuat=new A}setInitState(){this._dstRestQuat.copy(this.destination.quaternion),xt(this._invDstRestQuat.copy(this._dstRestQuat)),xt(this._invSrcRestQuatMulDstRestQuat.copy(this.source.quaternion)).multiply(this._dstRestQuat)}update(){const e=Ro.copy(this._invDstRestQuat).multiply(this.source.quaternion).multiply(this._invSrcRestQuatMulDstRestQuat),t=yo.copy(this._v3RollAxis).applyQuaternion(e),i=To.setFromUnitVectors(t,this._v3RollAxis).premultiply(this._dstRestQuat).multiply(e);this.destination.quaternion.copy(this._dstRestQuat).slerp(i,this.weight)}},Ao=new Set(["1.0","1.0-beta"]),_i=class st{get name(){return st.EXTENSION_NAME}constructor(t,n){this.parser=t,this.helperRoot=n?.helperRoot}afterRoot(t){return kn(this,null,function*(){t.userData.vrmNodeConstraintManager=yield this._import(t)})}_import(t){return kn(this,null,function*(){var n;const i=this.parser.json;if(!(((n=i.extensionsUsed)==null?void 0:n.indexOf(st.EXTENSION_NAME))!==-1))return null;const o=new vo,s=yield this.parser.getDependencies("node");return s.forEach((l,a)=>{var u;const d=i.nodes[a],c=(u=d?.extensions)==null?void 0:u[st.EXTENSION_NAME];if(c==null)return;const h=c.specVersion;if(!Ao.has(h)){console.warn(`VRMNodeConstraintLoaderPlugin: Unknown ${st.EXTENSION_NAME} specVersion "${h}"`);return}const p=c.constraint;if(p.roll!=null){const f=this._importRollConstraint(l,s,p.roll);o.addConstraint(f)}else if(p.aim!=null){const f=this._importAimConstraint(l,s,p.aim);o.addConstraint(f)}else if(p.rotation!=null){const f=this._importRotationConstraint(l,s,p.rotation);o.addConstraint(f)}}),t.scene.updateMatrixWorld(),o.setInitState(),o})}_importRollConstraint(t,n,i){const{source:r,rollAxis:o,weight:s}=i,l=n[r],a=new So(t,l);if(o!=null&&(a.rollAxis=o),s!=null&&(a.weight=s),this.helperRoot){const u=new Ct(a);this.helperRoot.add(u)}return a}_importAimConstraint(t,n,i){const{source:r,aimAxis:o,weight:s}=i,l=n[r],a=new go(t,l);if(o!=null&&(a.aimAxis=o),s!=null&&(a.weight=s),this.helperRoot){const u=new Ct(a);this.helperRoot.add(u)}return a}_importRotationConstraint(t,n,i){const{source:r,weight:o}=i,s=n[r],l=new wo(t,s);if(o!=null&&(l.weight=o),this.helperRoot){const a=new Ct(l);this.helperRoot.add(a)}return l}};_i.EXTENSION_NAME="VRMC_node_constraint";var Eo=_i,ft=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())}),Jt=class{},Ot=new v,Ve=new v,vi=class extends Jt{get type(){return"capsule"}constructor(e){var t,n,i,r;super(),this.offset=(t=e?.offset)!=null?t:new v(0,0,0),this.tail=(n=e?.tail)!=null?n:new v(0,0,0),this.radius=(i=e?.radius)!=null?i:0,this.inside=(r=e?.inside)!=null?r:!1}calculateCollision(e,t,n,i){Ot.setFromMatrixPosition(e),Ve.subVectors(this.tail,this.offset).applyMatrix4(e),Ve.sub(Ot);const r=Ve.lengthSq();i.copy(t).sub(Ot);const o=Ve.dot(i);o<=0||(r<=o||Ve.multiplyScalar(o/r),i.sub(Ve));const s=i.length(),l=this.inside?this.radius-n-s:s-n-this.radius;return l<0&&(i.multiplyScalar(1/s),this.inside&&i.negate()),l}},Ut=new v,Hn=new de,Mi=class extends Jt{get type(){return"plane"}constructor(e){var t,n;super(),this.offset=(t=e?.offset)!=null?t:new v(0,0,0),this.normal=(n=e?.normal)!=null?n:new v(0,0,1)}calculateCollision(e,t,n,i){i.setFromMatrixPosition(e),i.negate().add(t),Hn.getNormalMatrix(e),Ut.copy(this.normal).applyNormalMatrix(Hn).normalize();const r=i.dot(Ut)-n;return i.copy(Ut),r}},Po=new v,xi=class extends Jt{get type(){return"sphere"}constructor(e){var t,n,i;super(),this.offset=(t=e?.offset)!=null?t:new v(0,0,0),this.radius=(n=e?.radius)!=null?n:0,this.inside=(i=e?.inside)!=null?i:!1}calculateCollision(e,t,n,i){i.subVectors(t,Po.setFromMatrixPosition(e));const r=i.length(),o=this.inside?this.radius-n-r:r-n-this.radius;return o<0&&(i.multiplyScalar(1/r),this.inside&&i.negate()),o}},ue=new v,Lo=class extends ve{constructor(e){super(),this.worldScale=1,this._currentRadius=0,this._currentOffset=new v,this._currentTail=new v,this._shape=e,this._attrPos=new X(new Float32Array(396),3),this.setAttribute("position",this._attrPos),this._attrIndex=new X(new Uint16Array(264),1),this.setIndex(this._attrIndex),this._buildIndex(),this.update()}update(){let e=!1;const t=this._shape.radius/this.worldScale;this._currentRadius!==t&&(this._currentRadius=t,e=!0),this._currentOffset.equals(this._shape.offset)||(this._currentOffset.copy(this._shape.offset),e=!0);const n=ue.copy(this._shape.tail).divideScalar(this.worldScale);this._currentTail.distanceToSquared(n)>1e-10&&(this._currentTail.copy(n),e=!0),e&&this._buildPosition()}_buildPosition(){ue.copy(this._currentTail).sub(this._currentOffset);const e=ue.length()/this._currentRadius;for(let i=0;i<=16;i++){const r=i/16*Math.PI;this._attrPos.setXYZ(i,-Math.sin(r),-Math.cos(r),0),this._attrPos.setXYZ(17+i,e+Math.sin(r),Math.cos(r),0),this._attrPos.setXYZ(34+i,-Math.sin(r),0,-Math.cos(r)),this._attrPos.setXYZ(51+i,e+Math.sin(r),0,Math.cos(r))}for(let i=0;i<32;i++){const r=i/16*Math.PI;this._attrPos.setXYZ(68+i,0,Math.sin(r),Math.cos(r)),this._attrPos.setXYZ(100+i,e,Math.sin(r),Math.cos(r))}const t=Math.atan2(ue.y,Math.sqrt(ue.x*ue.x+ue.z*ue.z)),n=-Math.atan2(ue.z,ue.x);this.rotateZ(t),this.rotateY(n),this.scale(this._currentRadius,this._currentRadius,this._currentRadius),this.translate(this._currentOffset.x,this._currentOffset.y,this._currentOffset.z),this._attrPos.needsUpdate=!0}_buildIndex(){for(let e=0;e<34;e++){const t=(e+1)%34;this._attrIndex.setXY(e*2,e,t),this._attrIndex.setXY(68+e*2,34+e,34+t)}for(let e=0;e<32;e++){const t=(e+1)%32;this._attrIndex.setXY(136+e*2,68+e,68+t),this._attrIndex.setXY(200+e*2,100+e,100+t)}this._attrIndex.needsUpdate=!0}},bo=class extends ve{constructor(e){super(),this.worldScale=1,this._currentOffset=new v,this._currentNormal=new v,this._shape=e,this._attrPos=new X(new Float32Array(6*3),3),this.setAttribute("position",this._attrPos),this._attrIndex=new X(new Uint16Array(10),1),this.setIndex(this._attrIndex),this._buildIndex(),this.update()}update(){let e=!1;this._currentOffset.equals(this._shape.offset)||(this._currentOffset.copy(this._shape.offset),e=!0),this._currentNormal.equals(this._shape.normal)||(this._currentNormal.copy(this._shape.normal),e=!0),e&&this._buildPosition()}_buildPosition(){this._attrPos.setXYZ(0,-.5,-.5,0),this._attrPos.setXYZ(1,.5,-.5,0),this._attrPos.setXYZ(2,.5,.5,0),this._attrPos.setXYZ(3,-.5,.5,0),this._attrPos.setXYZ(4,0,0,0),this._attrPos.setXYZ(5,0,0,.25),this.translate(this._currentOffset.x,this._currentOffset.y,this._currentOffset.z),this.lookAt(this._currentNormal),this._attrPos.needsUpdate=!0}_buildIndex(){this._attrIndex.setXY(0,0,1),this._attrIndex.setXY(2,1,2),this._attrIndex.setXY(4,2,3),this._attrIndex.setXY(6,3,0),this._attrIndex.setXY(8,4,5),this._attrIndex.needsUpdate=!0}},Io=class extends ve{constructor(e){super(),this.worldScale=1,this._currentRadius=0,this._currentOffset=new v,this._shape=e,this._attrPos=new X(new Float32Array(32*3*3),3),this.setAttribute("position",this._attrPos),this._attrIndex=new X(new Uint16Array(64*3),1),this.setIndex(this._attrIndex),this._buildIndex(),this.update()}update(){let e=!1;const t=this._shape.radius/this.worldScale;this._currentRadius!==t&&(this._currentRadius=t,e=!0),this._currentOffset.equals(this._shape.offset)||(this._currentOffset.copy(this._shape.offset),e=!0),e&&this._buildPosition()}_buildPosition(){for(let e=0;e<32;e++){const t=e/16*Math.PI;this._attrPos.setXYZ(e,Math.cos(t),Math.sin(t),0),this._attrPos.setXYZ(32+e,0,Math.cos(t),Math.sin(t)),this._attrPos.setXYZ(64+e,Math.sin(t),0,Math.cos(t))}this.scale(this._currentRadius,this._currentRadius,this._currentRadius),this.translate(this._currentOffset.x,this._currentOffset.y,this._currentOffset.z),this._attrPos.needsUpdate=!0}_buildIndex(){for(let e=0;e<32;e++){const t=(e+1)%32;this._attrIndex.setXY(e*2,e,t),this._attrIndex.setXY(64+e*2,32+e,32+t),this._attrIndex.setXY(128+e*2,64+e,64+t)}this._attrIndex.needsUpdate=!0}},Co=new v,Nt=class extends Xe{constructor(e){if(super(),this.matrixAutoUpdate=!1,this.collider=e,this.collider.shape instanceof xi)this._geometry=new Io(this.collider.shape);else if(this.collider.shape instanceof vi)this._geometry=new Lo(this.collider.shape);else if(this.collider.shape instanceof Mi)this._geometry=new bo(this.collider.shape);else throw new Error("VRMSpringBoneColliderHelper: Unknown collider shape type detected");const t=new Rt({color:16711935,depthTest:!1,depthWrite:!1});this._line=new Yt(this._geometry,t),this.add(this._line)}dispose(){this._geometry.dispose()}updateMatrixWorld(e){this.collider.updateWorldMatrix(!0,!1),this.matrix.copy(this.collider.matrixWorld);const t=this.matrix.elements;this._geometry.worldScale=Co.set(t[0],t[1],t[2]).length(),this._geometry.update(),super.updateMatrixWorld(e)}},Oo=class extends ve{constructor(e){super(),this.worldScale=1,this._currentRadius=0,this._currentTail=new v,this._springBone=e,this._attrPos=new X(new Float32Array(294),3),this.setAttribute("position",this._attrPos),this._attrIndex=new X(new Uint16Array(194),1),this.setIndex(this._attrIndex),this._buildIndex(),this.update()}update(){let e=!1;const t=this._springBone.settings.hitRadius/this.worldScale;this._currentRadius!==t&&(this._currentRadius=t,e=!0),this._currentTail.equals(this._springBone.initialLocalChildPosition)||(this._currentTail.copy(this._springBone.initialLocalChildPosition),e=!0),e&&this._buildPosition()}_buildPosition(){for(let e=0;e<32;e++){const t=e/16*Math.PI;this._attrPos.setXYZ(e,Math.cos(t),Math.sin(t),0),this._attrPos.setXYZ(32+e,0,Math.cos(t),Math.sin(t)),this._attrPos.setXYZ(64+e,Math.sin(t),0,Math.cos(t))}this.scale(this._currentRadius,this._currentRadius,this._currentRadius),this.translate(this._currentTail.x,this._currentTail.y,this._currentTail.z),this._attrPos.setXYZ(96,0,0,0),this._attrPos.setXYZ(97,this._currentTail.x,this._currentTail.y,this._currentTail.z),this._attrPos.needsUpdate=!0}_buildIndex(){for(let e=0;e<32;e++){const t=(e+1)%32;this._attrIndex.setXY(e*2,e,t),this._attrIndex.setXY(64+e*2,32+e,32+t),this._attrIndex.setXY(128+e*2,64+e,64+t)}this._attrIndex.setXY(192,96,97),this._attrIndex.needsUpdate=!0}},Uo=new v,No=class extends Xe{constructor(e){super(),this.matrixAutoUpdate=!1,this.springBone=e,this._geometry=new Oo(this.springBone);const t=new Rt({color:16776960,depthTest:!1,depthWrite:!1});this._line=new Yt(this._geometry,t),this.add(this._line)}dispose(){this._geometry.dispose()}updateMatrixWorld(e){this.springBone.bone.updateWorldMatrix(!0,!1),this.matrix.copy(this.springBone.bone.matrixWorld);const t=this.matrix.elements;this._geometry.worldScale=Uo.set(t[0],t[1],t[2]).length(),this._geometry.update(),super.updateMatrixWorld(e)}},Vt=class extends at{constructor(e){super(),this.colliderMatrix=new he,this.shape=e}updateWorldMatrix(e,t){super.updateWorldMatrix(e,t),Vo(this.colliderMatrix,this.matrixWorld,this.shape.offset)}};function Vo(e,t,n){const i=t.elements;e.copy(t),n&&(e.elements[12]=i[0]*n.x+i[4]*n.y+i[8]*n.z+i[12],e.elements[13]=i[1]*n.x+i[5]*n.y+i[9]*n.z+i[13],e.elements[14]=i[2]*n.x+i[6]*n.y+i[10]*n.z+i[14])}var Bo=new he;function Do(e){return e.invert?e.invert():e.getInverse(Bo.copy(e)),e}var ko=class{constructor(e){this._inverseCache=new he,this._shouldUpdateInverse=!0,this.matrix=e;const t={set:(n,i,r)=>(this._shouldUpdateInverse=!0,n[i]=r,!0)};this._originalElements=e.elements,e.elements=new Proxy(e.elements,t)}get inverse(){return this._shouldUpdateInverse&&(Do(this._inverseCache.copy(this.matrix)),this._shouldUpdateInverse=!1),this._inverseCache}revert(){this.matrix.elements=this._originalElements}},Bt=new he,We=new v,nt=new v,it=new v,rt=new v,Fo=new he,Ho=class{constructor(e,t,n={},i=[]){this._currentTail=new v,this._prevTail=new v,this._boneAxis=new v,this._worldSpaceBoneLength=0,this._center=null,this._initialLocalMatrix=new he,this._initialLocalRotation=new A,this._initialLocalChildPosition=new v;var r,o,s,l,a,u;this.bone=e,this.bone.matrixAutoUpdate=!1,this.child=t,this.settings={hitRadius:(r=n.hitRadius)!=null?r:0,stiffness:(o=n.stiffness)!=null?o:1,gravityPower:(s=n.gravityPower)!=null?s:0,gravityDir:(a=(l=n.gravityDir)==null?void 0:l.clone())!=null?a:new v(0,-1,0),dragForce:(u=n.dragForce)!=null?u:.4},this.colliderGroups=i}get dependencies(){const e=new Set,t=this.bone.parent;t&&e.add(t);for(let n=0;n<this.colliderGroups.length;n++)for(let i=0;i<this.colliderGroups[n].colliders.length;i++)e.add(this.colliderGroups[n].colliders[i]);return e}get center(){return this._center}set center(e){var t;(t=this._center)!=null&&t.userData.inverseCacheProxy&&(this._center.userData.inverseCacheProxy.revert(),delete this._center.userData.inverseCacheProxy),this._center=e,this._center&&(this._center.userData.inverseCacheProxy||(this._center.userData.inverseCacheProxy=new ko(this._center.matrixWorld)))}get initialLocalChildPosition(){return this._initialLocalChildPosition}get _parentMatrixWorld(){return this.bone.parent?this.bone.parent.matrixWorld:Bt}setInitState(){this._initialLocalMatrix.copy(this.bone.matrix),this._initialLocalRotation.copy(this.bone.quaternion),this.child?this._initialLocalChildPosition.copy(this.child.position):this._initialLocalChildPosition.copy(this.bone.position).normalize().multiplyScalar(.07);const e=this._getMatrixWorldToCenter();this.bone.localToWorld(this._currentTail.copy(this._initialLocalChildPosition)).applyMatrix4(e),this._prevTail.copy(this._currentTail),this._boneAxis.copy(this._initialLocalChildPosition).normalize()}reset(){this.bone.quaternion.copy(this._initialLocalRotation),this.bone.updateMatrix(),this.bone.matrixWorld.multiplyMatrices(this._parentMatrixWorld,this.bone.matrix);const e=this._getMatrixWorldToCenter();this.bone.localToWorld(this._currentTail.copy(this._initialLocalChildPosition)).applyMatrix4(e),this._prevTail.copy(this._currentTail)}update(e){if(e<=0)return;this._calcWorldSpaceBoneLength();const t=nt.copy(this._boneAxis).transformDirection(this._initialLocalMatrix).transformDirection(this._parentMatrixWorld);rt.copy(this._currentTail).add(We.subVectors(this._currentTail,this._prevTail).multiplyScalar(1-this.settings.dragForce)).applyMatrix4(this._getMatrixCenterToWorld()).addScaledVector(t,this.settings.stiffness*e).addScaledVector(this.settings.gravityDir,this.settings.gravityPower*e),it.setFromMatrixPosition(this.bone.matrixWorld),rt.sub(it).normalize().multiplyScalar(this._worldSpaceBoneLength).add(it),this._collision(rt),this._prevTail.copy(this._currentTail),this._currentTail.copy(rt).applyMatrix4(this._getMatrixWorldToCenter());const n=Fo.multiplyMatrices(this._parentMatrixWorld,this._initialLocalMatrix).invert();this.bone.quaternion.setFromUnitVectors(this._boneAxis,We.copy(rt).applyMatrix4(n).normalize()).premultiply(this._initialLocalRotation),this.bone.updateMatrix(),this.bone.matrixWorld.multiplyMatrices(this._parentMatrixWorld,this.bone.matrix)}_collision(e){for(let t=0;t<this.colliderGroups.length;t++)for(let n=0;n<this.colliderGroups[t].colliders.length;n++){const i=this.colliderGroups[t].colliders[n],r=i.shape.calculateCollision(i.colliderMatrix,e,this.settings.hitRadius,We);if(r<0){e.addScaledVector(We,-r),e.sub(it);const o=e.length();e.multiplyScalar(this._worldSpaceBoneLength/o).add(it)}}}_calcWorldSpaceBoneLength(){We.setFromMatrixPosition(this.bone.matrixWorld),this.child?nt.setFromMatrixPosition(this.child.matrixWorld):(nt.copy(this._initialLocalChildPosition),nt.applyMatrix4(this.bone.matrixWorld)),this._worldSpaceBoneLength=We.sub(nt).length()}_getMatrixCenterToWorld(){return this._center?this._center.matrixWorld:Bt}_getMatrixWorldToCenter(){return this._center?this._center.userData.inverseCacheProxy.inverse:Bt}};function Wo(e,t){const n=[];let i=e;for(;i!==null;)n.unshift(i),i=i.parent;n.forEach(r=>{t(r)})}function Xt(e,t){e.children.forEach(n=>{t(n)||Xt(n,t)})}function zo(e){var t;const n=new Map;for(const i of e){let r=i;do{const o=((t=n.get(r))!=null?t:0)+1;if(o===e.size)return r;n.set(r,o),r=r.parent}while(r!==null)}return null}var Wn=class{constructor(){this._joints=new Set,this._sortedJoints=[],this._hasWarnedCircularDependency=!1,this._ancestors=[],this._objectSpringBonesMap=new Map,this._isSortedJointsDirty=!1,this._relevantChildrenUpdated=this._relevantChildrenUpdated.bind(this)}get joints(){return this._joints}get springBones(){return console.warn("VRMSpringBoneManager: springBones is deprecated. use joints instead."),this._joints}get colliderGroups(){const e=new Set;return this._joints.forEach(t=>{t.colliderGroups.forEach(n=>{e.add(n)})}),Array.from(e)}get colliders(){const e=new Set;return this.colliderGroups.forEach(t=>{t.colliders.forEach(n=>{e.add(n)})}),Array.from(e)}addJoint(e){this._joints.add(e);let t=this._objectSpringBonesMap.get(e.bone);t==null&&(t=new Set,this._objectSpringBonesMap.set(e.bone,t)),t.add(e),this._isSortedJointsDirty=!0}addSpringBone(e){console.warn("VRMSpringBoneManager: addSpringBone() is deprecated. use addJoint() instead."),this.addJoint(e)}deleteJoint(e){this._joints.delete(e),this._objectSpringBonesMap.get(e.bone).delete(e),this._isSortedJointsDirty=!0}deleteSpringBone(e){console.warn("VRMSpringBoneManager: deleteSpringBone() is deprecated. use deleteJoint() instead."),this.deleteJoint(e)}setInitState(){this._sortJoints();for(let e=0;e<this._sortedJoints.length;e++){const t=this._sortedJoints[e];t.bone.updateMatrix(),t.bone.updateWorldMatrix(!1,!1),t.setInitState()}}reset(){this._sortJoints();for(let e=0;e<this._sortedJoints.length;e++){const t=this._sortedJoints[e];t.bone.updateMatrix(),t.bone.updateWorldMatrix(!1,!1),t.reset()}}update(e){this._sortJoints();for(let t=0;t<this._ancestors.length;t++)this._ancestors[t].updateWorldMatrix(t===0,!1);for(let t=0;t<this._sortedJoints.length;t++){const n=this._sortedJoints[t];n.bone.updateMatrix(),n.bone.updateWorldMatrix(!1,!1),n.update(e),Xt(n.bone,this._relevantChildrenUpdated)}}_sortJoints(){if(!this._isSortedJointsDirty)return;const e=[],t=new Set,n=new Set,i=new Set;for(const o of this._joints)this._insertJointSort(o,t,n,e,i);this._sortedJoints=e;const r=zo(i);this._ancestors=[],r&&(this._ancestors.push(r),Xt(r,o=>{var s,l;return((l=(s=this._objectSpringBonesMap.get(o))==null?void 0:s.size)!=null?l:0)>0?!0:(this._ancestors.push(o),!1)})),this._isSortedJointsDirty=!1}_insertJointSort(e,t,n,i,r){if(n.has(e))return;if(t.has(e)){this._hasWarnedCircularDependency||(console.warn("VRMSpringBoneManager: Circular dependency detected"),this._hasWarnedCircularDependency=!0);return}t.add(e);const o=e.dependencies;for(const s of o){let l=!1,a=null;Wo(s,u=>{const d=this._objectSpringBonesMap.get(u);if(d)for(const c of d)l=!0,this._insertJointSort(c,t,n,i,r);else l||(a=u)}),a&&r.add(a)}i.push(e),n.add(e)}_relevantChildrenUpdated(e){var t,n;return((n=(t=this._objectSpringBonesMap.get(e))==null?void 0:t.size)!=null?n:0)>0?!0:(e.updateWorldMatrix(!1,!1),!1)}},zn="VRMC_springBone_extended_collider",jo=new Set(["1.0","1.0-beta"]),qo=new Set(["1.0"]),wi=class je{get name(){return je.EXTENSION_NAME}constructor(t,n){var i;this.parser=t,this.jointHelperRoot=n?.jointHelperRoot,this.colliderHelperRoot=n?.colliderHelperRoot,this.useExtendedColliders=(i=n?.useExtendedColliders)!=null?i:!0}afterRoot(t){return ft(this,null,function*(){t.userData.vrmSpringBoneManager=yield this._import(t)})}_import(t){return ft(this,null,function*(){const n=yield this._v1Import(t);if(n!=null)return n;const i=yield this._v0Import(t);return i??null})}_v1Import(t){return ft(this,null,function*(){var n,i,r,o,s;const l=t.parser.json;if(!(((n=l.extensionsUsed)==null?void 0:n.indexOf(je.EXTENSION_NAME))!==-1))return null;const u=new Wn,d=yield t.parser.getDependencies("node"),c=(i=l.extensions)==null?void 0:i[je.EXTENSION_NAME];if(!c)return null;const h=c.specVersion;if(!jo.has(h))return console.warn(`VRMSpringBoneLoaderPlugin: Unknown ${je.EXTENSION_NAME} specVersion "${h}"`),null;const p=(r=c.colliders)==null?void 0:r.map((m,_)=>{var g,M,y,x,R,T,S,P,U,L,N,F,Z,Y,Me;const J=d[m.node];if(J==null)return console.warn(`VRMSpringBoneLoaderPlugin: The collider #${_} attempted to reference a node #${m.node} but not found. Skipping the collider`),null;const Q=m.shape,K=(g=m.extensions)==null?void 0:g[zn];if(this.useExtendedColliders&&K!=null){const ie=K.specVersion;if(!qo.has(ie))console.warn(`VRMSpringBoneLoaderPlugin: Unknown ${zn} specVersion "${ie}". Fallbacking to the ${je.EXTENSION_NAME} definition`);else{const H=K.shape;if(H.sphere)return this._importSphereCollider(J,{offset:new v().fromArray((M=H.sphere.offset)!=null?M:[0,0,0]),radius:(y=H.sphere.radius)!=null?y:0,inside:(x=H.sphere.inside)!=null?x:!1});if(H.capsule)return this._importCapsuleCollider(J,{offset:new v().fromArray((R=H.capsule.offset)!=null?R:[0,0,0]),radius:(T=H.capsule.radius)!=null?T:0,tail:new v().fromArray((S=H.capsule.tail)!=null?S:[0,0,0]),inside:(P=H.capsule.inside)!=null?P:!1});if(H.plane)return this._importPlaneCollider(J,{offset:new v().fromArray((U=H.plane.offset)!=null?U:[0,0,0]),normal:new v().fromArray((L=H.plane.normal)!=null?L:[0,0,1])})}}if(Q.sphere)return this._importSphereCollider(J,{offset:new v().fromArray((N=Q.sphere.offset)!=null?N:[0,0,0]),radius:(F=Q.sphere.radius)!=null?F:0,inside:!1});if(Q.capsule)return this._importCapsuleCollider(J,{offset:new v().fromArray((Z=Q.capsule.offset)!=null?Z:[0,0,0]),radius:(Y=Q.capsule.radius)!=null?Y:0,tail:new v().fromArray((Me=Q.capsule.tail)!=null?Me:[0,0,0]),inside:!1});console.warn(`VRMSpringBoneLoaderPlugin: The collider #${_} has no valid shape. Skipping the collider`)}),f=(o=c.colliderGroups)==null?void 0:o.map((m,_)=>{var g;return{colliders:((g=m.colliders)!=null?g:[]).map(y=>{const x=p?.[y];return x??(console.warn(`VRMSpringBoneLoaderPlugin: The collider group #${_} attempted to reference a collider #${y} but not found. Skipping the collider`),null)}).filter(y=>y!=null),name:m.name}});return(s=c.springs)==null||s.forEach((m,_)=>{var g;const M=m.joints,y=(g=m.colliderGroups)==null?void 0:g.map(T=>{const S=f?.[T];return S??(console.warn(`VRMSpringBoneLoaderPlugin: The spring #${_} attempted to reference a collider group #${T} but not found. Skipping the collider group`),null)}).filter(T=>T!=null),x=m.center!=null?d[m.center]:void 0;let R;M.forEach(T=>{if(R){const S=R.node,P=d[S],U=T.node,L=d[U],N={hitRadius:R.hitRadius,dragForce:R.dragForce,gravityPower:R.gravityPower,stiffness:R.stiffness,gravityDir:R.gravityDir!=null?new v().fromArray(R.gravityDir):void 0},F=this._importJoint(P,L,N,y);x&&(F.center=x),u.addJoint(F)}R=T})}),u.setInitState(),u})}_v0Import(t){return ft(this,null,function*(){var n,i,r;const o=t.parser.json;if(!(((n=o.extensionsUsed)==null?void 0:n.indexOf("VRM"))!==-1))return null;const l=(i=o.extensions)==null?void 0:i.VRM,a=l?.secondaryAnimation;if(!a)return null;const u=a?.boneGroups;if(!u)return null;const d=new Wn,c=yield t.parser.getDependencies("node"),h=(r=a.colliderGroups)==null?void 0:r.map((p,f)=>{var m;const _=c[p.node];return _==null?(console.warn(`VRMSpringBoneLoaderPlugin: The collider group #${f} attempted to reference a node #${p.node} but not found. Skipping the collider group`),null):{colliders:((m=p.colliders)!=null?m:[]).map((M,y)=>{var x,R,T;const S=new v(0,0,0);return M.offset&&S.set((x=M.offset.x)!=null?x:0,(R=M.offset.y)!=null?R:0,M.offset.z?-M.offset.z:0),this._importSphereCollider(_,{offset:S,radius:(T=M.radius)!=null?T:0,inside:!1})})}});return u?.forEach((p,f)=>{const m=p.bones;m&&m.forEach(_=>{var g,M,y,x;const R=c[_];if(R==null){console.warn(`VRMSpringBoneLoaderPlugin: The spring bone group #${f} attempted to reference a node #${_} but not found. Skipping the node`);return}const T=new v;p.gravityDir?T.set((g=p.gravityDir.x)!=null?g:0,(M=p.gravityDir.y)!=null?M:0,(y=p.gravityDir.z)!=null?y:0):T.set(0,-1,0);const S=p.center!=null?c[p.center]:void 0,P={hitRadius:p.hitRadius,dragForce:p.dragForce,gravityPower:p.gravityPower,stiffness:p.stiffiness,gravityDir:T},U=(x=p.colliderGroups)==null?void 0:x.map(L=>{const N=h?.[L];return N??(console.warn(`VRMSpringBoneLoaderPlugin: The spring #${f} attempted to reference a collider group #${L} but not found. Skipping the collider group`),null)}).filter(L=>L!=null);R.traverse(L=>{var N;const F=(N=L.children[0])!=null?N:null,Z=this._importJoint(L,F,P,U);S&&(Z.center=S),d.addJoint(Z)})})}),t.scene.updateMatrixWorld(),d.setInitState(),d})}_importJoint(t,n,i,r){const o=new Ho(t,n,i,r);if(this.jointHelperRoot){const s=new No(o);this.jointHelperRoot.add(s),s.renderOrder=this.jointHelperRoot.renderOrder}return o}_importSphereCollider(t,n){const i=new xi(n),r=new Vt(i);if(t.add(r),this.colliderHelperRoot){const o=new Nt(r);this.colliderHelperRoot.add(o),o.renderOrder=this.colliderHelperRoot.renderOrder}return r}_importCapsuleCollider(t,n){const i=new vi(n),r=new Vt(i);if(t.add(r),this.colliderHelperRoot){const o=new Nt(r);this.colliderHelperRoot.add(o),o.renderOrder=this.colliderHelperRoot.renderOrder}return r}_importPlaneCollider(t,n){const i=new Mi(n),r=new Vt(i);if(t.add(r),this.colliderHelperRoot){const o=new Nt(r);this.colliderHelperRoot.add(o),o.renderOrder=this.colliderHelperRoot.renderOrder}return r}};wi.EXTENSION_NAME="VRMC_springBone";var Xo=wi,Go=class{get name(){return"VRMLoaderPlugin"}constructor(e,t){var n,i,r,o,s,l,a,u,d,c;this.parser=e;const h=t?.helperRoot,p=t?.autoUpdateHumanBones;this.expressionPlugin=(n=t?.expressionPlugin)!=null?n:new lr(e),this.firstPersonPlugin=(i=t?.firstPersonPlugin)!=null?i:new dr(e),this.humanoidPlugin=(r=t?.humanoidPlugin)!=null?r:new _r(e,{helperRoot:h,autoUpdateHumanBones:p}),this.lookAtPlugin=(o=t?.lookAtPlugin)!=null?o:new Cr(e,{helperRoot:h}),this.metaPlugin=(s=t?.metaPlugin)!=null?s:new Nr(e),this.mtoonMaterialPlugin=(l=t?.mtoonMaterialPlugin)!=null?l:new $r(e),this.materialsHDREmissiveMultiplierPlugin=(a=t?.materialsHDREmissiveMultiplierPlugin)!=null?a:new Jr(e),this.materialsV0CompatPlugin=(u=t?.materialsV0CompatPlugin)!=null?u:new oo(e),this.springBonePlugin=(d=t?.springBonePlugin)!=null?d:new Xo(e,{colliderHelperRoot:h,jointHelperRoot:h}),this.nodeConstraintPlugin=(c=t?.nodeConstraintPlugin)!=null?c:new Eo(e,{helperRoot:h})}beforeRoot(){return ct(this,null,function*(){yield this.materialsV0CompatPlugin.beforeRoot(),yield this.mtoonMaterialPlugin.beforeRoot()})}loadMesh(e){return ct(this,null,function*(){return yield this.mtoonMaterialPlugin.loadMesh(e)})}getMaterialType(e){const t=this.mtoonMaterialPlugin.getMaterialType(e);return t??null}extendMaterialParams(e,t){return ct(this,null,function*(){yield this.materialsHDREmissiveMultiplierPlugin.extendMaterialParams(e,t),yield this.mtoonMaterialPlugin.extendMaterialParams(e,t)})}afterRoot(e){return ct(this,null,function*(){yield this.metaPlugin.afterRoot(e),yield this.humanoidPlugin.afterRoot(e),yield this.expressionPlugin.afterRoot(e),yield this.lookAtPlugin.afterRoot(e),yield this.firstPersonPlugin.afterRoot(e),yield this.springBonePlugin.afterRoot(e),yield this.nodeConstraintPlugin.afterRoot(e),yield this.mtoonMaterialPlugin.afterRoot(e);const t=e.userData.vrmMeta,n=e.userData.vrmHumanoid;if(t&&n){const i=new Br({scene:e.scene,expressionManager:e.userData.vrmExpressionManager,firstPerson:e.userData.vrmFirstPerson,humanoid:n,lookAt:e.userData.vrmLookAt,meta:t,materials:e.userData.vrmMToonMaterials,springBoneManager:e.userData.vrmSpringBoneManager,nodeConstraintManager:e.userData.vrmNodeConstraintManager});e.userData.vrm=i}})}};function Yo(e){const t=new Set;return e.traverse(n=>{if(!n.isMesh)return;const i=n;t.add(i)}),t}function jn(e,t,n){if(t.size===1){const s=t.values().next().value;if(s.weight===1)return e[s.index]}const i=new Float32Array(e[0].count*3);let r=0;if(n)r=1;else for(const s of t)r+=s.weight;for(const s of t){const l=e[s.index],a=s.weight/r;for(let u=0;u<l.count;u++)i[u*3+0]+=l.getX(u)*a,i[u*3+1]+=l.getY(u)*a,i[u*3+2]+=l.getZ(u)*a}return new X(i,3)}function Qo(e){var t;const n=Yo(e.scene),i=new Map,r=(t=e.expressionManager)==null?void 0:t.expressionMap;if(r!=null)for(const[o,s]of Object.entries(r)){const l=new Set;for(const a of s.binds)if(a instanceof Mt){if(a.weight!==0)for(const u of a.primitives){let d=i.get(u);d==null&&(d=new Map,i.set(u,d));let c=d.get(o);c==null&&(c=new Set,d.set(o,c)),c.add(a)}l.add(a)}for(const a of l)s.deleteBind(a)}for(const o of n){const s=i.get(o);if(s==null)continue;const l=o.geometry.morphAttributes;o.geometry.morphAttributes={};const a=o.geometry.clone();o.geometry=a;const u=a.morphTargetsRelative,d=l.position!=null,c=l.normal!=null,h={},p={},f=[];if(d||c){d&&(h.position=[]),c&&(h.normal=[]);let m=0;for(const[_,g]of s)d&&(h.position[m]=jn(l.position,g,u)),c&&(h.normal[m]=jn(l.normal,g,u)),r?.[_].addBind(new Mt({index:m,weight:1,primitives:[o]})),p[_]=m,f.push(0),m++}a.morphAttributes=h,o.morphTargetDictionary=p,o.morphTargetInfluences=f}}function wt(e,t,n){if(e.getComponent)return e.getComponent(t,n);{let i=e.array[t*e.itemSize+n];return e.normalized&&(i=V.denormalize(i,e.array)),i}}function yi(e,t,n,i){e.setComponent?e.setComponent(t,n,i):(e.normalized&&(i=V.normalize(i,e.array)),e.array[t*e.itemSize+n]=i)}function $o(e){var t;const n=Zo(e),i=new Set;for(const c of n)i.has(c.geometry)&&(c.geometry=is(c.geometry)),i.add(c.geometry);const r=new Map;for(const c of i){const h=c.getAttribute("skinIndex"),p=(t=r.get(h))!=null?t:new Map;r.set(h,p);const f=c.getAttribute("skinWeight"),m=Jo(h,f);p.set(f,m)}const o=new Map;for(const c of n){const h=Ko(c,r);o.set(c,h)}const s=[];for(const[c,h]of o){let p=!1;for(const f of s)if(es(h,f.boneInverseMap)){p=!0,f.meshes.add(c);for(const[_,g]of h)f.boneInverseMap.set(_,g);break}p||s.push({boneInverseMap:h,meshes:new Set([c])})}const l=new Map,a=new Dt,u=new Dt,d=new Dt;for(const c of s){const{boneInverseMap:h,meshes:p}=c,f=Array.from(h.keys()),m=Array.from(h.values()),_=new Qt(f,m),g=u.getOrCreate(_);for(const M of p){const y=M.geometry.getAttribute("skinIndex"),x=a.getOrCreate(y),R=M.skeleton.bones,T=R.map(U=>d.getOrCreate(U)).join(","),S=`${x};${g};${T}`;let P=l.get(S);P==null&&(P=y.clone(),ts(P,R,f),l.set(S,P)),M.geometry.setAttribute("skinIndex",P)}for(const M of p)M.bind(_,new he)}}function Zo(e){const t=new Set;return e.traverse(n=>{if(!n.isSkinnedMesh)return;const i=n;t.add(i)}),t}function Jo(e,t){const n=new Set;for(let i=0;i<e.count;i++)for(let r=0;r<e.itemSize;r++){const o=wt(e,i,r);wt(t,i,r)!==0&&n.add(o)}return n}function Ko(e,t){const n=new Map,i=e.skeleton,r=e.geometry,o=r.getAttribute("skinIndex"),s=r.getAttribute("skinWeight"),l=t.get(o),a=l?.get(s);if(!a)throw new Error("Unreachable. attributeUsedIndexSetMap does not know the skin index attribute or the skin weight attribute.");for(const u of a)n.set(i.bones[u],i.boneInverses[u]);return n}function es(e,t){for(const[n,i]of e.entries()){const r=t.get(n);if(r!=null&&!ns(i,r))return!1}return!0}function ts(e,t,n){const i=new Map;for(const o of t)i.set(o,i.size);const r=new Map;for(const[o,s]of n.entries()){const l=i.get(s);r.set(l,o)}for(let o=0;o<e.count;o++)for(let s=0;s<e.itemSize;s++){const l=wt(e,o,s),a=r.get(l);yi(e,o,s,a)}e.needsUpdate=!0}function ns(e,t,n){if(n=n||1e-4,e.elements.length!=t.elements.length)return!1;for(let i=0,r=e.elements.length;i<r;i++)if(Math.abs(e.elements[i]-t.elements[i])>n)return!1;return!0}var Dt=class{constructor(){this._objectIndexMap=new Map,this._index=0}get(e){return this._objectIndexMap.get(e)}getOrCreate(e){let t=this._objectIndexMap.get(e);return t==null&&(t=this._index,this._objectIndexMap.set(e,t),this._index++),t}};function is(e){var t,n,i,r;const o=new ve;o.name=e.name,o.setIndex(e.index);for(const[s,l]of Object.entries(e.attributes))o.setAttribute(s,l);for(const[s,l]of Object.entries(e.morphAttributes)){const a=s;o.morphAttributes[a]=l.concat()}o.morphTargetsRelative=e.morphTargetsRelative,o.groups=[];for(const s of e.groups)o.addGroup(s.start,s.count,s.materialIndex);return o.boundingSphere=(n=(t=e.boundingSphere)==null?void 0:t.clone())!=null?n:null,o.boundingBox=(r=(i=e.boundingBox)==null?void 0:i.clone())!=null?r:null,o.drawRange.start=e.drawRange.start,o.drawRange.count=e.drawRange.count,o.userData=e.userData,o}function qn(e){if(Object.values(e).forEach(t=>{t?.isTexture&&t.dispose()}),e.isShaderMaterial){const t=e.uniforms;t&&Object.values(t).forEach(n=>{const i=n.value;i?.isTexture&&i.dispose()})}e.dispose()}function rs(e){const t=e.geometry;t&&t.dispose();const n=e.skeleton;n&&n.dispose();const i=e.material;i&&(Array.isArray(i)?i.forEach(r=>qn(r)):i&&qn(i))}function os(e){e.traverse(rs)}function ss(e,t){var n,i;console.warn("VRMUtils.removeUnnecessaryJoints: removeUnnecessaryJoints is deprecated. Use combineSkeletons instead. combineSkeletons contributes more to the performance improvement. This function will be removed in the next major version.");const r=(n=t?.experimentalSameBoneCounts)!=null?n:!1,o=[];e.traverse(a=>{a.type==="SkinnedMesh"&&o.push(a)});const s=new Map;let l=0;for(const a of o){const d=a.geometry.getAttribute("skinIndex");if(s.has(d))continue;const c=new Map,h=new Map;for(let p=0;p<d.count;p++)for(let f=0;f<d.itemSize;f++){const m=wt(d,p,f);let _=c.get(m);_==null&&(_=c.size,c.set(m,_),h.set(_,m)),yi(d,p,f,_)}d.needsUpdate=!0,s.set(d,h),l=Math.max(l,c.size)}for(const a of o){const d=a.geometry.getAttribute("skinIndex"),c=s.get(d),h=[],p=[],f=r?l:c.size;for(let _=0;_<f;_++){const g=(i=c.get(_))!=null?i:0;h.push(a.skeleton.bones[g]),p.push(a.skeleton.boneInverses[g])}const m=new Qt(h,p);a.bind(m,new he)}}function as(e,t){const n=e.position.count,i=new Array(n);let r=0;const o=t.array;for(let s=0;s<o.length;s++){const l=o[s];i[l]||(i[l]=!0,r++)}return{isVertexUsed:i,vertexCount:n,verticesUsed:r}}function ls(e){const t=[],n=[];let i=0;for(let r=0;r<e.length;r++)if(e[r]){const o=i++;t[r]=o,n[o]=r}return{originalIndexNewIndexMap:t,newIndexOriginalIndexMap:n}}function us(e,t){var n,i,r,o;t.name=e.name,t.morphTargetsRelative=e.morphTargetsRelative,e.groups.forEach(s=>{t.addGroup(s.start,s.count,s.materialIndex)}),t.boundingBox=(i=(n=e.boundingBox)==null?void 0:n.clone())!=null?i:null,t.boundingSphere=(o=(r=e.boundingSphere)==null?void 0:r.clone())!=null?o:null,t.setDrawRange(e.drawRange.start,e.drawRange.count),t.userData=e.userData}function ds(e,t,n){const i=t.array,r=new i.constructor(i.length);for(let o=0;o<i.length;o++){const s=i[o];r[o]=n[s]}e.setIndex(new X(r,t.itemSize,t.normalized))}function yt(e,t,n){const i=e.constructor,r=new i(t.length*n);let o=!0;for(let s=0;s<t.length;s++){const a=t[s]*n,u=s*n;for(let d=0;d<n;d++){const c=e[a+d];r[u+d]=c,o=o&&c===0}}return[r,o]}function cs(e){var t;const n=new Map,i=[];for(const[r,o]of Object.entries(e))if(o.isInterleavedBufferAttribute){const s=o,l=s.data,a=(t=n.get(l))!=null?t:[];n.set(l,a),a.push([r,s])}else{const s=o;i.push([r,s])}return[n,i]}function hs(e,t,n){const[i,r]=cs(t);for(const[o,s]of i){const l=o.array,{stride:a}=o,[u]=yt(l,n,a),d=new $n(u,a);d.setUsage(o.usage);for(const[c,h]of s){const{itemSize:p,offset:f,normalized:m}=h,_=new Zn(d,p,f,m);e.setAttribute(c,_)}}for(const[o,s]of r){const l=s.array,{itemSize:a,normalized:u}=s,[d]=yt(l,n,a);e.setAttribute(o,new X(d,a,u))}}function ps(e){var t;const n=new Map,i=[];for(const[r,o]of Object.entries(e)){const s=r;for(let l=0;l<o.length;l++){const a=o[l];if(a.isInterleavedBufferAttribute){const u=a,d=u.data,c=(t=n.get(d))!=null?t:[];n.set(d,c),c.push([s,l,u])}else{const u=a;i.push([s,l,u])}}}return[n,i]}function fs(e,t,n){var i,r;let o=!0;const[s,l]=ps(t),a={};for(const[u,d]of s){const c=u.array,{stride:h}=u,[p,f]=yt(c,n,h);o=o&&f;const m=new $n(p,h);m.setUsage(u.usage);for(const[_,g,M]of d){const{itemSize:y,offset:x,normalized:R}=M,T=new Zn(m,y,x,R);(i=a[_])!=null||(a[_]=[]),a[_][g]=T}}for(const[u,d,c]of l){const h=c,p=h.array,{itemSize:f,normalized:m}=h,[_,g]=yt(p,n,f);o=o&&g,(r=a[u])!=null||(a[u]=[]),a[u][d]=new X(_,f,m)}e.morphAttributes=o?{}:a}function ms(e){const t=new Map;e.traverse(n=>{if(!n.isMesh)return;const i=n,r=i.geometry,o=r.index;if(o==null)return;const s=t.get(r);if(s!=null){i.geometry=s;return}const{isVertexUsed:l,vertexCount:a,verticesUsed:u}=as(r.attributes,o);if(u===a)return;const{originalIndexNewIndexMap:d,newIndexOriginalIndexMap:c}=ls(l),h=new ve;us(r,h),t.set(r,h),ds(h,o,d),hs(h,r.attributes,c),fs(h,r.morphAttributes,c),i.geometry=h}),Array.from(t.keys()).forEach(n=>{n.dispose()})}function gs(e){var t;((t=e.meta)==null?void 0:t.metaVersion)==="0"&&(e.scene.rotation.y=Math.PI)}var ce=class{constructor(){}};ce.combineMorphs=Qo;ce.combineSkeletons=$o;ce.deepDispose=os;ce.removeUnnecessaryJoints=ss;ce.removeUnnecessaryVertices=ms;ce.rotateVRM0=gs;/*!
 * @pixiv/three-vrm-core v3.5.5
 * The implementation of core features of VRM, for @pixiv/three-vrm
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-core is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 *//*!
 * @pixiv/three-vrm-materials-mtoon v3.5.5
 * MToon (toon material) module for @pixiv/three-vrm
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-materials-mtoon is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 *//*!
 * @pixiv/three-vrm-materials-hdr-emissive-multiplier v3.5.5
 * Support VRMC_hdr_emissiveMultiplier for @pixiv/three-vrm
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-materials-hdr-emissive-multiplier is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 *//*!
 * @pixiv/three-vrm-materials-v0compat v3.5.5
 * VRM0.0 materials compatibility layer plugin for @pixiv/three-vrm
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-materials-v0compat is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 *//*!
 * @pixiv/three-vrm-node-constraint v3.5.5
 * Node constraint module for @pixiv/three-vrm
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-node-constraint is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 *//*!
 * @pixiv/three-vrm-springbone v3.5.5
 * Spring bone module for @pixiv/three-vrm
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-springbone is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 *//*!
 * @pixiv/three-vrm-animation v3.5.5
 * The implementation of VRM Animation
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-animation is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 */var Xn=(e,t,n)=>new Promise((i,r)=>{var o=a=>{try{l(n.next(a))}catch(u){r(u)}},s=a=>{try{l(n.throw(a))}catch(u){r(u)}},l=a=>a.done?i(a.value):Promise.resolve(a.value).then(o,s);l((n=n.apply(e,t)).next())}),_s={Aa:"aa",Ih:"ih",Ou:"ou",Ee:"ee",Oh:"oh",Blink:"blink",Happy:"happy",Angry:"angry",Sad:"sad",Relaxed:"relaxed",LookUp:"lookUp",Surprised:"surprised",LookDown:"lookDown",LookLeft:"lookLeft",LookRight:"lookRight",BlinkLeft:"blinkLeft",BlinkRight:"blinkRight",Neutral:"neutral"};new ne;var Gn={hips:null,spine:"hips",chest:"spine",upperChest:"chest",neck:"upperChest",head:"neck",leftEye:"head",rightEye:"head",jaw:"head",leftUpperLeg:"hips",leftLowerLeg:"leftUpperLeg",leftFoot:"leftLowerLeg",leftToes:"leftFoot",rightUpperLeg:"hips",rightLowerLeg:"rightUpperLeg",rightFoot:"rightLowerLeg",rightToes:"rightFoot",leftShoulder:"upperChest",leftUpperArm:"leftShoulder",leftLowerArm:"leftUpperArm",leftHand:"leftLowerArm",rightShoulder:"upperChest",rightUpperArm:"rightShoulder",rightLowerArm:"rightUpperArm",rightHand:"rightLowerArm",leftThumbMetacarpal:"leftHand",leftThumbProximal:"leftThumbMetacarpal",leftThumbDistal:"leftThumbProximal",leftIndexProximal:"leftHand",leftIndexIntermediate:"leftIndexProximal",leftIndexDistal:"leftIndexIntermediate",leftMiddleProximal:"leftHand",leftMiddleIntermediate:"leftMiddleProximal",leftMiddleDistal:"leftMiddleIntermediate",leftRingProximal:"leftHand",leftRingIntermediate:"leftRingProximal",leftRingDistal:"leftRingIntermediate",leftLittleProximal:"leftHand",leftLittleIntermediate:"leftLittleProximal",leftLittleDistal:"leftLittleIntermediate",rightThumbMetacarpal:"rightHand",rightThumbProximal:"rightThumbMetacarpal",rightThumbDistal:"rightThumbProximal",rightIndexProximal:"rightHand",rightIndexIntermediate:"rightIndexProximal",rightIndexDistal:"rightIndexIntermediate",rightMiddleProximal:"rightHand",rightMiddleIntermediate:"rightMiddleProximal",rightMiddleDistal:"rightMiddleIntermediate",rightRingProximal:"rightHand",rightRingIntermediate:"rightRingProximal",rightRingDistal:"rightRingIntermediate",rightLittleProximal:"rightHand",rightLittleIntermediate:"rightLittleProximal",rightLittleDistal:"rightLittleIntermediate"};function vs(e,t,n){var i,r;const o=new Map,s=new Map;for(const[l,a]of e.humanoidTracks.rotation.entries()){const u=(i=t.getNormalizedBoneNode(l))==null?void 0:i.name;if(u!=null){const d=new Ft(`${u}.quaternion`,a.times,a.values.map((c,h)=>n==="0"&&h%2===0?-c:c));s.set(l,d)}}for(const[l,a]of e.humanoidTracks.translation.entries()){const u=(r=t.getNormalizedBoneNode(l))==null?void 0:r.name;if(u!=null){const d=e.restHipsPosition.y,h=t.normalizedRestPose.hips.position[1]/d,p=a.clone();p.values=p.values.map((f,m)=>(n==="0"&&m%3!==1?-f:f)*h),p.name=`${u}.position`,o.set(l,p)}}return{translation:o,rotation:s}}var Ms=class{constructor(){this.duration=0,this.restHipsPosition=new v,this.humanoidTracks={translation:new Map,rotation:new Map},this.expressionTracks={preset:new Map,custom:new Map},this.lookAtTrack=null}};function Yn(e,t){const n=e.length,i=[];let r=[],o=0;for(let s=0;s<n;s++){const l=e[s];o<=0&&(o=t,r=[],i.push(r)),r.push(l),o--}return i}var xs=new he,ot=new v,kt=new A,Qn=new A,ws=new A,ys=new Set(["1.0","1.0-draft"]),Rs=new Set(Object.values(_s)),Ts=class{constructor(e){this.parser=e}get name(){return"VRMC_vrm_animation"}afterRoot(e){return Xn(this,null,function*(){var t,n,i;const r=e.parser.json,o=r.extensionsUsed;if(o==null||o.indexOf(this.name)==-1)return;const s=(t=r.extensions)==null?void 0:t[this.name];if(s==null)return;const l=s.specVersion;if(l==null)console.warn("VRMAnimationLoaderPlugin: specVersion of the VRMA is not defined. Consider updating the animation file. Assuming the spec version is 1.0.");else{if(!ys.has(l)){console.warn(`VRMAnimationLoaderPlugin: Unknown VRMC_vrm_animation spec version: ${l}`);return}l==="1.0-draft"&&console.warn("VRMAnimationLoaderPlugin: Using a draft spec version: 1.0-draft. Some behaviors may be different. Consider updating the animation file.")}const a=this._createNodeMap(s),u=yield this._createBoneWorldMatrixMap(e,s),d=(i=(n=s.humanoid)==null?void 0:n.humanBones.hips)==null?void 0:i.node,c=d!=null?yield e.parser.getDependency("node",d):null,h=new v;c?.getWorldPosition(h),h.y<.001&&console.warn("VRMAnimationLoaderPlugin: The loaded VRM Animation might violate the VRM T-pose (The y component of the rest hips position is approximately zero or below.)");const f=e.animations.map((m,_)=>{const g=r.animations[_],M=this._parseAnimation(m,g,a,u);return M.restHipsPosition=h,M});e.userData.vrmAnimations=f})}_createNodeMap(e){var t,n,i,r,o;const s=new Map,l=new Map,a=(t=e.humanoid)==null?void 0:t.humanBones;a&&Object.entries(a).forEach(([h,p])=>{const f=p?.node;f!=null&&s.set(f,h)});const u=(n=e.expressions)==null?void 0:n.preset;u&&Object.entries(u).forEach(([h,p])=>{const f=p?.node;f!=null&&l.set(f,h)});const d=(i=e.expressions)==null?void 0:i.custom;d&&Object.entries(d).forEach(([h,p])=>{const{node:f}=p;l.set(f,h)});const c=(o=(r=e.lookAt)==null?void 0:r.node)!=null?o:null;return{humanoidIndexToName:s,expressionsIndexToName:l,lookAtIndex:c}}_createBoneWorldMatrixMap(e,t){return Xn(this,null,function*(){var n,i;e.scene.updateWorldMatrix(!1,!0);const r=yield e.parser.getDependencies("node"),o=new Map;if(t.humanoid==null)return o;for(const[s,l]of Object.entries(t.humanoid.humanBones)){const a=l?.node;if(a!=null){const u=r[a];o.set(s,u.matrixWorld),s==="hips"&&o.set("hipsParent",(i=(n=u.parent)==null?void 0:n.matrixWorld)!=null?i:xs)}}return o})}_parseAnimation(e,t,n,i){const r=e.tracks,o=t.channels,s=new Ms;return s.duration=e.duration,o.forEach((l,a)=>{const{node:u,path:d}=l.target,c=r[a];if(u==null)return;const h=n.humanoidIndexToName.get(u);if(h!=null){let f=Gn[h];for(;f!=null&&i.get(f)==null;)f=Gn[f];if(f==null&&(f="hipsParent"),d==="translation")if(h!=="hips")console.warn(`The loading animation contains a translation track for ${h}, which is not permitted in the VRMC_vrm_animation spec. ignoring the track`);else{const m=i.get("hipsParent"),_=Yn(c.values,3).flatMap(M=>ot.fromArray(M).applyMatrix4(m).toArray()),g=c.clone();g.values=new Float32Array(_),s.humanoidTracks.translation.set(h,g)}else if(d==="rotation"){const m=i.get(h),_=i.get(f);m.decompose(ot,kt,ot),kt.invert(),_.decompose(ot,Qn,ot);const g=Yn(c.values,4).flatMap(y=>ws.fromArray(y).premultiply(Qn).multiply(kt).toArray()),M=c.clone();M.values=new Float32Array(g),s.humanoidTracks.rotation.set(h,M)}else throw new Error(`Invalid path "${d}"`);return}const p=n.expressionsIndexToName.get(u);if(p!=null){if(d==="translation"){const f=c.times,m=new Float32Array(c.values.length/3);for(let g=0;g<m.length;g++)m[g]=c.values[3*g];const _=new Yi(`${p}.weight`,f,m);Rs.has(p)?s.expressionTracks.preset.set(p,_):s.expressionTracks.custom.set(p,_)}else throw new Error(`Invalid path "${d}"`);return}if(u===n.lookAtIndex)if(d==="rotation")s.lookAtTrack=c;else throw new Error(`Invalid path "${d}"`)}),s}};/*!
 * @pixiv/three-vrm-core v3.5.5
 * The implementation of core features of VRM, for @pixiv/three-vrm
 *
 * Copyright (c) 2019-2026 pixiv Inc.
 * @pixiv/three-vrm-core is distributed under MIT License
 * https://github.com/pixiv/three-vrm/blob/release/LICENSE
 */const Ss=10*1024*1024;function As(e){if(e.byteLength>Ss)throw new Error("Animation must be at most 10 MiB.");if(e.byteLength<28)throw new Error("Upload a binary VRMA file.");const t=new DataView(e),n=t.getUint32(12,!0);if(t.getUint32(0,!0)!==1179937895||t.getUint32(4,!0)!==2||t.getUint32(8,!0)!==e.byteLength||t.getUint32(16,!0)!==1313821514||n>2*1024*1024||n+28>e.byteLength)throw new Error("Invalid VRMA container.");const i=28+n,r=t.getUint32(20+n,!0);if(t.getUint32(24+n,!0)!==5130562||i+r!==e.byteLength)throw new Error("Invalid animation binary data.");const o=JSON.parse(new TextDecoder().decode(new Uint8Array(e,20,n))),s=o.extensions?.VRMC_vrm_animation,l=Object.values(s?.humanoid?.humanBones??{});if(s?.specVersion!=null&&s.specVersion!=="1.0"||!l.length||!o.nodes?.length||o.nodes.length>512||l.some(g=>!Number.isInteger(g.node)||!o.nodes[g.node]))throw new Error("Use a VRMA 1.0 humanoid animation.");const a=new Set,u=new Set,d=new Set,c=g=>{if(!Number.isInteger(g)||!o.nodes[g]||u.has(g))throw new Error("Invalid animation node hierarchy.");if(d.has(g))return;u.add(g);const M=o.nodes[g];for(const[y,x]of Object.entries({translation:3,rotation:4,scale:3,matrix:16}))if(M[y]&&(M[y].length!==x||M[y].some(R=>!Number.isFinite(R))))throw new Error("Invalid animation transform.");for(const y of M.children??[]){if(a.has(y))throw new Error("Animation nodes must have a single parent.");a.add(y),c(y)}u.delete(g),d.add(g)};o.nodes.forEach((g,M)=>c(M));for(const g of o.scenes??[])if((g.nodes??[]).some(M=>!Number.isInteger(M)||!o.nodes[M]))throw new Error("Invalid animation scene.");if(o.buffers?.length!==1||"uri"in o.buffers[0]||o.buffers[0].byteLength>r||o.buffers[0].byteLength<r-3||["images","textures","meshes","skins"].some(g=>o[g]?.length)||(o.extensionsRequired??[]).some(g=>g!=="VRMC_vrm_animation"))throw new Error("Export embedded animation only, without meshes or textures.");for(const g of o.bufferViews??[])if((g.buffer??0)!==0||(g.byteOffset??0)<0||!(g.byteLength>0)||(g.byteOffset??0)+g.byteLength>r)throw new Error("Invalid animation buffer.");let h=0;const p=(o.accessors??[]).map(g=>{h+=g.count;const M={SCALAR:1,VEC3:3,VEC4:4}[g.type],y=o.bufferViews?.[g.bufferView],x=y?.byteStride??M*4,R=g.byteOffset??0;if(!Number.isInteger(g.count)||g.count<=0||h>5e5||g.sparse||g.componentType!==5126||!M||!y||x<M*4||x%4||R<0||R+(g.count-1)*x+M*4>y.byteLength)throw new Error("Invalid animation keyframes.");return Array.from({length:g.count},(T,S)=>Array.from({length:M},(P,U)=>{const L=t.getFloat32(i+(y.byteOffset??0)+R+S*x+U*4,!0);if(!Number.isFinite(L))throw new Error("Animation keyframes must be finite.");return L}))}),f=o.animations?.[0];if(o.animations?.length!==1||!f?.channels?.length||f.channels.length>256)throw new Error("Export exactly one animation per VRMA file.");let m=0,_=!1;for(const g of f.channels){const M=g.target,y=f.samplers?.[g.sampler],x=p[y?.input],R=p[y?.output],T=y?.interpolation??"LINEAR";if(!["LINEAR","STEP"].includes(T))throw new Error("Export baked animation with linear or stepped keyframes.");if(!o.nodes[M?.node]||!["rotation","translation"].includes(M.path)||!x||!R||o.accessors[y.input].type!=="SCALAR"||!["LINEAR","STEP"].includes(T)||R.length!==x.length||R[0].length!==(M.path==="rotation"?4:3)||x.some((S,P)=>S[0]<0||P>0&&S[0]<=x[P-1][0]))throw new Error("Invalid animation channels or timing.");m=Math.max(m,x[x.length-1][0]),_||=l.some(S=>S.node===M.node)}if(!_||m<=0||m>60)throw new Error("Use a body animation between 0 and 60 seconds.")}async function Es(e,t){As(e);const n=new Jn;n.setURLModifier(()=>{throw new Error("External animation resources are not supported.")});const i=new ei(n);i.register(u=>new Ts(u));const o=(await i.parseAsync(e,"")).userData.vrmAnimations?.[0];if(!o||!Number.isFinite(o.restHipsPosition.y)||o.restHipsPosition.y<=0)throw new Error("Animation needs a valid humanoid rest pose.");const s=vs(o,t.humanoid,t.meta.metaVersion);for(const[u,d]of s.rotation)d.setInterpolation(o.humanoidTracks.rotation.get(u).getInterpolation());const l=[...s.rotation.values(),...s.translation.values()];if(!l.length)throw new Error("Animation has no compatible body tracks.");const a=t.humanoid.getNormalizedBoneNode("hips");for(const u of l)if(u.name.endsWith(".position"))for(let d=0;d<u.values.length;d+=3)u.values[d]=a.position.x,u.values[d+2]=a.position.z;return new Kn("body",o.duration,l)}async function Cs(e,t,n){await rr(t),n.throwIfAborted();const i=new Jn;i.setURLModifier(w=>{if(!w.startsWith("blob:"))throw new Error("External avatar resources are not supported.");return w});const r=new ei(i);r.register(w=>new Go(w));const o=await r.parseAsync(t,""),s=o.userData.vrm;if(!s||n.aborted)throw ce.deepDispose(o.scene),n.throwIfAborted(),new Error("This VRM could not be loaded.");ce.rotateVRM0(s);const l=new Qi;l.add(s.scene),l.add(new $i(16777215,9147039,2));const a=new Zi(16777215,2.2);a.position.set(-1,2,3),l.add(a);let u;try{u=new Ji({canvas:e,alpha:!0,antialias:!0,powerPreference:"low-power"})}catch(w){throw ce.deepDispose(s.scene),w}u.setPixelRatio(Math.min(window.devicePixelRatio||1,2)),u.setClearColor(0,0),u.outputColorSpace=Ki;const d=new er(30,1,.01,100),c=w=>s.humanoid.getNormalizedBoneNode(w),h=s.meta.metaVersion==="0"?-1:1,p=c("head"),f=c("spine"),m=c("chest")??c("upperChest"),_=c("leftUpperArm"),g=c("rightUpperArm"),M=c("leftLowerArm"),y=c("rightLowerArm"),x=c("hips");s.scene.updateMatrixWorld(!0);const R=["left","right"].flatMap(w=>{const b=c(`${w}UpperLeg`),E=c(`${w}LowerLeg`),B=c(`${w}Foot`);return!b||!E||!B?[]:[{upper:b,lower:E,foot:B,target:B.getWorldPosition(new v),orientation:B.getWorldQuaternion(new A)}]}),T={hips:[0,0,.025],spine:[.025,.015,-.035],chest:[-.012,-.008,.01],head:[.008,-.008,0],leftShoulder:[0,0,-.025],rightShoulder:[0,0,.035],leftUpperArm:[.025,-.06,-1.38],rightUpperArm:[-.015,.035,1.34],leftLowerArm:[0,-.24,-.035],rightLowerArm:[0,.19,.025],leftHand:[.025,0,-.055],rightHand:[-.015,0,.035],leftUpperLeg:[-.025,0,.045],rightUpperLeg:[-.045,0,0],leftLowerLeg:[.05,0,0],rightLowerLeg:[.09,0,0],leftFoot:[-.025,.045,-.02],rightFoot:[-.045,-.035,.025]};for(const[w,b]of Object.entries(T))c(w)?.rotation.set(b[0]*h,b[1],b[2]*h);for(const w of["left","right"]){const b=w==="left"?-1:1;for(const[E,B]of["Index","Middle","Ring","Little"].entries()){const C=.18+E*.035+(w==="right"?.025:0);for(const[k,q]of[["Proximal",C],["Intermediate",C*.8],["Distal",.04]]){const G=c(`${w}${B}${k}`);G&&(G.rotation.z=b*q*h)}}}if(x&&R.length===2){const w=x.getWorldPosition(new v).y-(R[0].target.y+R[1].target.y)/2;if(w>0){const b=x.getWorldPosition(new v);b.x+=w*.02,b.y-=w*.009,x.position.copy(x.parent?x.parent.worldToLocal(b):b)}}s.scene.updateMatrixWorld(!0);const S=(w,b,E)=>{const B=w.getWorldPosition(new v),C=b.getWorldPosition(new v).sub(B).normalize(),k=E.clone().sub(B).normalize(),q=new A().setFromUnitVectors(C,k).multiply(w.getWorldQuaternion(new A)),G=w.parent?.getWorldQuaternion(new A)??new A;w.quaternion.copy(G.invert().multiply(q)),w.updateWorldMatrix(!1,!0)};for(const{upper:w,lower:b,foot:E,target:B,orientation:C}of R){const k=w.getWorldPosition(new v),q=b.getWorldPosition(new v),G=k.distanceTo(q),$=q.distanceTo(E.getWorldPosition(new v));if(G<.001||$<.001)continue;const se=B.clone().sub(k),j=V.clamp(se.length(),Math.abs(G-$)+1e-4,G+$-1e-4);se.normalize();const _e=(G**2+j**2-$**2)/(2*j),be=new v(0,0,1).addScaledVector(se,-se.z).normalize();q.copy(k).addScaledVector(se,_e).addScaledVector(be,Math.sqrt(Math.max(0,G**2-_e**2))),S(w,b,q),S(b,E,B);const Ie=E.parent?.getWorldQuaternion(new A)??new A;E.quaternion.copy(Ie.invert().multiply(C)),E.updateWorldMatrix(!1,!0)}s.update(0),s.scene.updateMatrixWorld(!0);const P=new tr().setFromObject(s.scene),U=P.getSize(new v),L=P.getCenter(new v),N=p?.getWorldPosition(new v)??L.clone(),F=Math.max(U.y,.5),Z=new at;l.add(Z),s.lookAt&&(s.lookAt.target=Z);const Y=s.expressionManager,Me=!!Y?.getExpression("aa"),J=!!Y?.getExpression("blink"),Q=!!Y?.getExpression("blinkLeft")&&!!Y?.getExpression("blinkRight");let K=0,ie=0,H=0,D=0,Ge=2.8,Ye=-10,Te=0,re=0;const ee=new nr(s.scene),pe=Object.values(s.humanoid.normalizedHumanBones).map(({node:w})=>({node:w,restQ:w.quaternion.clone(),restP:w.position.clone(),q:w.quaternion.clone(),p:w.position.clone(),authoredQ:w.quaternion.clone(),authoredP:w.position.clone()})),Se=new Map;let W=null,z=null,De=0,fe=0,me=0,xe=!1,Ae=0,ge=!0,Ee=0,Pe=0,Le=0,oe=0,we=1;const ke=new qe,lt=(w,b)=>{if(z&&(z.stop(),ee.uncacheAction(z.getClip()),z=null),W){W.stop();const E=new Kn("transition",.3,pe.flatMap(({node:B,authoredQ:C,authoredP:k})=>[new Ft(`${B.name}.quaternion`,[0],C.toArray()),new un(`${B.name}.position`,[0],k.toArray())]));z=ee.clipAction(E).play()}W=ee.clipAction(w),W.reset().setLoop(b?ln:ir,b?1:1/0),W.clampWhenFinished=!0,W.enabled=!0,W.setEffectiveWeight(1).play(),z&&z!==W&&W.crossFadeFrom(z,.3,!1),De=0},Qe=()=>{xe=!1,Ae=0,me=0};return{capabilities:{mouth:Me,blink:J||Q},async loadAnimation(w,b){const E=await Es(b,s);n.throwIfAborted();const B=new Set(E.tracks.map(C=>C.name));for(const{node:C,restQ:k,restP:q}of pe)B.has(`${C.name}.quaternion`)||E.tracks.push(new Ft(`${C.name}.quaternion`,[0],k.toArray())),B.has(`${C.name}.position`)||E.tracks.push(new un(`${C.name}.position`,[0],q.toArray()));Se.set(w,E)},playGesture(w){if(!ge)return"unavailable";const b=Se.get(w);return b?(lt(b,!0),xe=!0,Ae=0,"started"):"unavailable"},cancelGesture:Qe,rotateView(w,b){const E=2*Math.PI/Math.max(re,1);Pe-=w*E,Le=V.clamp(Le+b*E,-1.3,1.3),oe=0},spinView(w){oe=-w*2*Math.PI/Math.max(re,1)},panView(w,b){const E=2*Ee*we*Math.tan(V.degToRad(d.fov/2))/Math.max(re,1);ke.x-=w*E,ke.y+=b*E},zoomView(w){we=V.clamp(we*w,.3,3)},resetView(){Pe=Le=oe=0,we=1,ke.set(0,0)},render(w,b,E,B){const C=Math.min(w,.05);D+=C,ge=E.active&&!B,ge||Qe(),E.speaking&&E.active?me=.2:me=Math.max(0,me-C),E.listening&&(me=0);const k=E.speaking||me>0?"speaking":E.listening?"listening":"idle";xe&&(Ae+=C,Ae>=W.getClip().duration&&Qe());const q=ge?Se.get(b.states?.[k]?.file_id??""):void 0;!xe&&q&&(W?.getClip()!==q||W.loop===ln)&&lt(q,!1);const G=ge&&(xe||!!q);fe=V.clamp(fe+(G?C:-C)/.3,0,1),ge||(fe=0);for(const O of pe)O.node.quaternion.copy(O.restQ),O.node.position.copy(O.restP);const $=e.getBoundingClientRect();if(!$.width||!$.height)return;($.width!==Te||$.height!==re)&&(Te=$.width,re=$.height,u.setSize(Te,re,!1),d.aspect=Te/re,d.updateProjectionMatrix());const se=1-Math.exp(-C*5);K+=((E.active&&E.speaking?1:0)-K)*se,ie+=((E.active&&E.listening&&!E.speaking?1:0)-ie)*se;const j=B?0:Math.sqrt(.35),_e=Math.sin(D*1.1)*.9+Math.sin(D*.47)*.1,be=j*(.01*Math.sin(D*.43)+.003*Math.sin(D*.71));if(f&&(f.rotation.x+=h*j*(.006*_e+.015*ie),f.rotation.y+=j*K*.008*Math.sin(D*.6),f.rotation.z+=h*be),m&&(m.rotation.x-=h*j*.008*_e,m.rotation.z-=h*be*.35),p&&(p.rotation.x+=h*j*(.006*_e+K*.012*Math.sin(D*.85)+ie*.025),p.rotation.y+=j*(.012*Math.sin(D*.32)+K*.008*Math.sin(D*.6)),p.rotation.z+=h*(j*(.006*Math.sin(D*.27)+ie*.025)-be*.5)),_&&(_.rotation.z+=h*j*.004*_e),g&&(g.rotation.z-=h*j*.003*Math.sin(D*1.1-.2)),M&&(M.rotation.y-=j*.006*Math.sin(D*1.1-.3)),y&&(y.rotation.y+=j*.004*Math.sin(D*1.1-.5)),W&&(fe>0||G)){for(const O of pe)O.q.copy(O.node.quaternion),O.p.copy(O.node.position),O.node.quaternion.copy(O.authoredQ),O.node.position.copy(O.authoredP);ee.update(C),De+=C,z&&De>=.3&&(z.stop(),ee.uncacheAction(z.getClip()),z=null);for(const O of pe)O.authoredQ.copy(O.node.quaternion),O.authoredP.copy(O.node.position),O.node.quaternion.slerpQuaternions(O.q,O.authoredQ,fe),O.node.position.lerpVectors(O.p,O.authoredP,fe)}else W&&(ee.stopAllAction(),z&&ee.uncacheAction(z.getClip()),W=z=null);const Ie=E.active&&E.speaking?Math.min(1,Math.max(0,E.level)*7)*.7:0;H=Ie===0?0:H+(Ie-H)*(1-Math.exp(-C*24)),Me&&Y.setValue("aa",H),D>=Ge&&(Ye=D,Ge=D+3.2+Math.random()*2.8);const $e=(D-Ye)/.17,Ze=$e>=0&&$e<=1?Math.sin($e*Math.PI):0;J?Y.setValue("blink",Ze):Q&&(Y.setValue("blinkLeft",Ze),Y.setValue("blinkRight",Ze)),s.lookAt&&(s.lookAt.autoUpdate=!0),Z.position.set(d.position.x+j*.1*Math.sin(D*.4),N.y,d.position.z),s.update(B?0:C),s.scene.updateMatrixWorld(!0);const Ce=P.clone(),Tt=new v;for(const{node:O}of pe)Ce.expandByPoint(O.getWorldPosition(Tt));Ce.expandByScalar(F*.06);const ye=Ce.getSize(new v),Oe=Ce.getCenter(new v),ut=Math.max(F,ye.y+2*Math.abs(Oe.y-L.y)),St=Math.max(U.x,ye.x+2*Math.abs(Oe.x-L.x)),Je=Math.max(U.z,ye.z)/2+Math.max(ut,St/d.aspect)*1.2/(2*Math.tan(Math.PI/12));Ee=Math.max(Je,Ee),oe=B||Math.abs(oe)<.01?0:oe*Math.exp(-C*3),Pe+=oe*C,d.position.setFromSphericalCoords(Ee*we,Math.PI/2-Le,Pe).add(L),d.lookAt(L),d.translateX(ke.x),d.translateY(ke.y),u.render(l,d)},dispose(){ee.stopAllAction(),ee.uncacheRoot(s.scene),Se.clear(),ce.deepDispose(s.scene),u.dispose(),u.forceContextLoss()}}}export{Cs as createAvatarRenderer};
//# sourceMappingURL=2U_YjaxO.js.map
