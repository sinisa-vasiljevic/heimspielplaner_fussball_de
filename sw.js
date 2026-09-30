'use strict';
const CACHE_NAME='heimspielplaner-v48.0-fussballde';
const APP_SHELL=['./index.html','./manifest.webmanifest','./version.json','./icon-192.png','./icon-512.png','./apple-touch-icon.png'];
self.addEventListener('install',event=>event.waitUntil((async()=>{const c=await caches.open(CACHE_NAME);await c.addAll(APP_SHELL);await self.skipWaiting()})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const k of await caches.keys())if(k.startsWith('heimspielplaner-')&&k!==CACHE_NAME)await caches.delete(k);await self.clients.claim()})()));
self.addEventListener('fetch',event=>{const r=event.request;if(r.method!=='GET')return;const u=new URL(r.url);if(u.origin!==self.location.origin)return;
 if(u.pathname.endsWith('/spiele-live.json')||u.pathname.endsWith('/version.json')){event.respondWith((async()=>{const c=await caches.open(CACHE_NAME);try{const n=await fetch(r,{cache:'no-store'});if(n.ok)await c.put(u.pathname.split('/').pop(),n.clone());return n}catch(e){return (await c.match(u.pathname.split('/').pop()))||new Response('',{status:503})}})());return}
 if(r.mode==='navigate'){event.respondWith((async()=>{const c=await caches.open(CACHE_NAME);try{const n=await fetch(r);if(n.ok)await c.put('./index.html',n.clone());return n}catch(e){return (await c.match('./index.html'))||new Response('Offline',{status:503})}})());return}
 event.respondWith((async()=>{const c=await caches.open(CACHE_NAME);const hit=await c.match(r,{ignoreSearch:true});if(hit)return hit;try{const n=await fetch(r);if(n.ok)await c.put(r,n.clone());return n}catch(e){return new Response('',{status:503})}})())});
