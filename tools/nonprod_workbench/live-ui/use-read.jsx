import {useEffect,useRef,useState} from 'react';
import {resource} from './live-state.mjs';
import {createSharedPoller} from '../ui/shared-view.mjs';

export function useRead(key,loader,interval=true) {
  const ref=useRef(null);if(!ref.current)ref.current=resource();
  const reader=ref.current,[state,setState]=useState(()=>reader.value()),latest=useRef({key,loader});
  latest.current={key,loader};
  useEffect(()=>reader.subscribe(()=>setState(reader.value())),[reader]);
  useEffect(()=>{
    reader.invalidate();if(key===null)return;
    const poller=createSharedPoller({cadenceFromStart:true,yieldAfterRead:true,
      read:async()=>{await reader.read(key,loader);if(reader.value().error)throw Error(reader.value().error);},
      apply:()=>{},fail:()=>{}});
    if(interval)poller.refresh();else reader.read(key,loader);
    return()=>{poller.stop();reader.invalidate();};
  },[key]);
  function refresh(){
    const current=latest.current;if(current.key===null)return Promise.resolve();
    reader.invalidate(true);return reader.read(current.key,current.loader);
  }
  return {reader,key,state,data:state.key===key?state.data:null,fresh:reader.fresh(key),refresh};
}
