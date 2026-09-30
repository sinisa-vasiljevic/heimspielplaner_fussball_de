'use strict';
const CACHE_NAME='heimspielplaner-v49.2';
const APP_SHELL=[
  './index.html',
  './manifest.webmanifest?v=49.2',
  './version.json',
  './icon-192.png?v=49.2',
  './icon-512.png?v=49.2',
  './apple-touch-icon.png?v=49.2'
];
self.addEventListener('install',event=>event.waitUntil((async()=>{
  const cache=await caches.open(CACHE_NAME);
  await cache.addAll(APP_SHELL);
  await self.skipWaiting();
})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const key of await caches.keys()){
    if(key.startsWith('heimspielplaner-')&&key!==CACHE_NAME) await caches.delete(key);
  }
  await self.clients.claim();
})()));
self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET') return;
  const url=new URL(request.url);
  if(url.origin!==self.location.origin) return;
  if(/\/(spiele-live\.json|version\.json)$/.test(url.pathname)){
    event.respondWith((async()=>{
      const cache=await caches.open(CACHE_NAME);
      try{
        const response=await fetch(request,{cache:'no-store'});
        if(response.ok) await cache.put(request,response.clone());
        return response;
      }catch(error){
        return (await cache.match(request,{ignoreSearch:true}))||new Response('',{status:503});
      }
    })());
    return;
  }
  if(request.mode==='navigate'){
    event.respondWith((async()=>{
      const cache=await caches.open(CACHE_NAME);
      try{
        const response=await fetch(request,{cache:'no-store'});
        if(response.ok) await cache.put('./index.html',response.clone());
        return response;
      }catch(error){
        return (await cache.match('./index.html'))||new Response('Offline',{status:503});
      }
    })());
    return;
  }
  event.respondWith((async()=>{
    const cache=await caches.open(CACHE_NAME);
    try{
      const response=await fetch(request,{cache:'no-cache'});
      if(response.ok) await cache.put(request,response.clone());
      return response;
    }catch(error){
      return (await cache.match(request,{ignoreSearch:true}))||new Response('',{status:503});
    }
  })());
});
