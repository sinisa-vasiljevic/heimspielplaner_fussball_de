'use strict';
const CACHE_NAME='heimspielplaner-v46.0-offline';
const APP_SHELL=['./index.html','./manifest.webmanifest','./version.json','./icon-192.png','./icon-512.png','./apple-touch-icon.png'];

self.addEventListener('install',event=>{
  event.waitUntil((async()=>{
    const cache=await caches.open(CACHE_NAME);
    const results=await Promise.allSettled(APP_SHELL.map(async path=>{
      const response=await fetch(path,{cache:'reload'});
      if(!response.ok)throw new Error(path+' HTTP '+response.status);
      await cache.put(path,response);
    }));
    const indexResult=results[0];
    if(indexResult.status!=='fulfilled')throw indexResult.reason;
    await self.skipWaiting();
  })());
});

self.addEventListener('activate',event=>{
  event.waitUntil((async()=>{
    const keys=await caches.keys();
    await Promise.all(keys.filter(key=>key.startsWith('heimspielplaner-')&&key!==CACHE_NAME).map(key=>caches.delete(key)));
    await self.clients.claim();
  })());
});

async function cachedIndex(){
  const cache=await caches.open(CACHE_NAME);
  return (await cache.match('./index.html'))||(await cache.match('index.html'));
}

self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET')return;
  const url=new URL(request.url);

  if(request.mode==='navigate'){
    event.respondWith((async()=>{
      try{
        const response=await fetch(request);
        if(response&&response.ok){
          const cache=await caches.open(CACHE_NAME);
          await cache.put('./index.html',response.clone());
          return response;
        }
        return (await cachedIndex())||response;
      }catch(error){
        const cached=await cachedIndex();
        if(cached)return cached;
        return new Response('<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Heimspielplaner offline</title><body style="font-family:system-ui;padding:24px;background:#eef2f7;color:#0f172a"><h1>Heimspielplaner</h1><p>Die Offline-Dateien sind noch nicht vollständig gespeichert. Bitte die App einmal mit Internetverbindung öffnen und danach erneut versuchen.</p></body></html>',{status:503,headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'}});
      }
    })());
    return;
  }

  if(url.origin===self.location.origin){
    event.respondWith((async()=>{
      const cache=await caches.open(CACHE_NAME);
      const normalized=new Request(url.origin+url.pathname,{method:'GET'});
      const cached=(await cache.match(request,{ignoreSearch:true}))||(await cache.match(normalized,{ignoreSearch:true}));
      if(cached)return cached;
      try{
        const response=await fetch(request);
        if(response&&response.ok)await cache.put(normalized,response.clone());
        return response;
      }catch(error){
        return new Response('',{status:503,statusText:'Offline'});
      }
    })());
    return;
  }

  event.respondWith(fetch(request).catch(()=>new Response('',{status:503,statusText:'Offline'})));
});
