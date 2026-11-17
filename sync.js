import {initializeApp} from 'https://www.gstatic.com/firebasejs/12.4.0/firebase-app.js';
import {getAuth,setPersistence,browserLocalPersistence,signInWithEmailAndPassword,signOut,onAuthStateChanged} from 'https://www.gstatic.com/firebasejs/12.4.0/firebase-auth.js';
import {getFirestore,collection,getDocs,doc,writeBatch,serverTimestamp} from 'https://www.gstatic.com/firebasejs/12.4.0/firebase-firestore.js';

const cfg=window.HEIMSPIELPLANER_SYNC_CONFIG||{};
const info=document.getElementById('cloudSyncInfo');
const loggedOut=document.getElementById('cloudLoggedOut');
const loggedIn=document.getElementById('cloudLoggedIn');
const status=document.getElementById('cloudStatus');
let auth=null,db=null,currentUser=null,busy=false;
const localKey='hs_manual_games_v509';
const readLocal=()=>{try{const v=JSON.parse(localStorage.getItem(localKey)||'[]');return Array.isArray(v)?v:[]}catch{return[]}};
const writeLocal=games=>localStorage.setItem(localKey,JSON.stringify(games));
const setInfo=(text,kind='info')=>{if(!info)return;info.className='status '+kind;info.textContent=text};
const normalize=g=>({
  id:String(g.id),teamId:String(g.teamId||''),club:'vfr',label:String(g.label||''),date:String(g.date||''),time:String(g.time||''),
  opponent:String(g.opponent||''),venue:String(g.venue||''),pitch:String(g.pitch||''),surface:String(g.surface||'unbekannt'),
  source:'MANUELL',manualType:String(g.manualType||'Manuell'),locationType:['home','away','relocated'].includes(g.locationType)?g.locationType:'home',
  createdAt:g.createdAt||new Date().toISOString(),updatedAt:new Date().toISOString()
});
const valid=g=>g&&g.id&&/^\d{4}-\d{2}-\d{2}$/.test(g.date||'')&&/^([01]\d|2[0-3]):[0-5]\d$/.test(g.time||'');
async function loadRemote(){
  const snap=await getDocs(collection(db,cfg.collection||'manualGames'));
  return snap.docs.map(x=>x.data()).filter(valid).map(normalize);
}
async function saveAll(games){
  if(!currentUser||currentUser.uid!==cfg.masterUid||busy)return;
  busy=true;
  try{
    const clean=(Array.isArray(games)?games:[]).filter(valid).map(normalize),remote=await getDocs(collection(db,cfg.collection||'manualGames'));
    const keep=new Set(clean.map(g=>g.id));let batch=writeBatch(db),ops=0;
    for(const d of remote.docs){if(!keep.has(d.id)){batch.delete(d.ref);ops++;if(ops===450){await batch.commit();batch=writeBatch(db);ops=0}}}
    for(const g of clean){batch.set(doc(db,cfg.collection||'manualGames',g.id),{...g,syncedAt:serverTimestamp()},{merge:true});ops++;if(ops===450){await batch.commit();batch=writeBatch(db);ops=0}}
    if(ops)await batch.commit();
    setInfo(clean.length+' manuelle Spiele zentral gespeichert.','ok');
  }finally{busy=false}
}
async function mergeAndSync(){
  const local=readLocal(),remote=await loadRemote(),byId=new Map();
  [...remote,...local].forEach(g=>{if(valid(g))byId.set(String(g.id),normalize(g))});
  const merged=[...byId.values()].sort((a,b)=>(a.date+a.time).localeCompare(b.date+b.time));
  writeLocal(merged);window.dispatchEvent(new CustomEvent('manualgames-cloud-loaded',{detail:{games:merged}}));
  await saveAll(merged);
}
window.ManualGameCloud={saveAll,mergeAndSync,isConnected:()=>!!currentUser};
try{
  if(!cfg.firebaseConfig||!cfg.masterUid)throw new Error('Firebase-Konfiguration fehlt.');
  const app=initializeApp(cfg.firebaseConfig,'heimspielplaner-sync');auth=getAuth(app);db=getFirestore(app);await setPersistence(auth,browserLocalPersistence);
  document.getElementById('cloudLogin').onclick=async()=>{try{setInfo('Anmeldung läuft ...','loading');await signInWithEmailAndPassword(auth,document.getElementById('cloudEmail').value.trim(),document.getElementById('cloudPassword').value)}catch(e){setInfo('Anmeldung fehlgeschlagen: '+(e.code||e.message),'bad')}};
  document.getElementById('cloudLogout').onclick=()=>signOut(auth);
  document.getElementById('cloudSyncNow').onclick=()=>mergeAndSync().catch(e=>setInfo('Synchronisierung fehlgeschlagen: '+(e.code||e.message),'bad'));
  onAuthStateChanged(auth,async user=>{
    currentUser=user;const master=!!user&&user.uid===cfg.masterUid;loggedOut.style.display=master?'none':'block';loggedIn.style.display=master?'block':'none';
    if(user&&!master){setInfo('Dieses Konto ist nicht das hinterlegte Masterkonto.','bad');await signOut(auth);return}
    if(!master){setInfo('Noch nicht mit dem zentralen Spielspeicher verbunden.','info');return}
    status.textContent='Zentrale Speicherung ist aktiv: '+(user.email||'Masterkonto');
    try{await mergeAndSync()}catch(e){setInfo('Synchronisierung fehlgeschlagen: '+(e.code||e.message),'bad')}
  });
}catch(e){setInfo('Zentraler Spielspeicher konnte nicht gestartet werden: '+e.message,'bad')}
