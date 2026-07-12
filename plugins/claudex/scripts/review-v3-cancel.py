#!/usr/bin/env python3
"""Serialize review-v3 cancellation with spawn/publication and kill its group."""
import argparse, fcntl, os, pathlib, signal, tempfile, time

def atomic(path,text):
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.tmp.')
 with os.fdopen(fd,'w') as f: f.write(text); f.flush(); os.fsync(f.fileno())
 os.replace(tmp,path)
def main():
 p=argparse.ArgumentParser(); p.add_argument('state',type=pathlib.Path); p.add_argument('marker',type=pathlib.Path); a=p.parse_args(); lock=a.state.with_name(a.state.name+'.write-lock')
 with lock.open('a+') as held:
  fcntl.flock(held,fcntl.LOCK_EX); lines=a.state.read_text().splitlines(); out=[]
  for line in lines:
   k=line.split(':',1)[0]; replacements={'phase':'cancelled','decision_signal':'cancelled','clean':'false','coverage_complete':'false','revision_required':'false'}
   out.append(f'{k}: {replacements[k]}' if k in replacements else line)
  atomic(a.state,'\n'.join(out)+'\n')
  try: raw=a.marker.read_text().strip(); pgid=int(raw)
  except (OSError,ValueError): return
  try: os.killpg(pgid,signal.SIGTERM)
  except ProcessLookupError: pass
  deadline=time.monotonic()+2
  while time.monotonic()<deadline:
   try: os.killpg(pgid,0)
   except ProcessLookupError: break
   time.sleep(.02)
  else:
   try: os.killpg(pgid,signal.SIGKILL)
   except ProcessLookupError: pass
if __name__=='__main__': main()
