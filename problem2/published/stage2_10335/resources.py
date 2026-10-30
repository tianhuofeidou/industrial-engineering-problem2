"""Six physical cores, one logical processor each; below-normal priority, own processes only."""
import ctypes,struct,os
from ctypes import wintypes
def kernel():
    k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetCurrentProcess.restype=wintypes.HANDLE
    k.GetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.GetProcessAffinityMask.restype=wintypes.BOOL
    k.SetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.c_size_t];k.SetProcessAffinityMask.restype=wintypes.BOOL
    k.SetPriorityClass.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.SetPriorityClass.restype=wintypes.BOOL
    k.GetPriorityClass.argtypes=[wintypes.HANDLE];k.GetPriorityClass.restype=wintypes.DWORD
    return k
def affinity():
    k=kernel();a=ctypes.c_size_t();b=ctypes.c_size_t()
    if not k.GetProcessAffinityMask(k.GetCurrentProcess(),ctypes.byref(a),ctypes.byref(b)):raise ctypes.WinError(ctypes.get_last_error())
    return a.value
def topology():
    k=kernel();f=k.GetLogicalProcessorInformationEx;f.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD)];f.restype=wintypes.BOOL
    n=wintypes.DWORD();f(0,None,ctypes.byref(n));buf=ctypes.create_string_buffer(n.value)
    if not f(0,buf,ctypes.byref(n)):raise ctypes.WinError(ctypes.get_last_error())
    cores=[];off=0
    while off<n.value:
        rel,size=struct.unpack_from('<II',buf.raw,off)
        if rel==0:
            count=struct.unpack_from('<H',buf.raw,off+30)[0]
            cores.append([dict(mask=mask,group=group) for mask,group in [struct.unpack_from('<QH',buf.raw,off+32+16*i) for i in range(count)]])
        off+=size
    return cores
def select():
    allowed=affinity();cores=topology();chosen=[]
    for core in cores:
        available=next((x['mask']&allowed for x in core if x['group']==0 and x['mask']&allowed),0)
        if available:chosen.append(available&-available)
    assert len(chosen)>=6,'Need six available physical cores'
    chosen=chosen[:6]
    return dict(physical_cores_detected=len(cores),logical_processors_detected=os.cpu_count(),available_affinity_mask=allowed,
        selected_affinity_mask=sum(chosen),selected_logical_processors=[x.bit_length()-1 for x in chosen],
        selected_physical_cores=6,gurobi_threads=6,priority_class=0x4000,priority='BELOW_NORMAL',one_logical_processor_per_physical_core=True)
def apply(config):
    k=kernel();handle=k.GetCurrentProcess()
    if not k.SetProcessAffinityMask(handle,config['selected_affinity_mask']):raise ctypes.WinError(ctypes.get_last_error())
    if not k.SetPriorityClass(handle,config['priority_class']):raise ctypes.WinError(ctypes.get_last_error())
    assert affinity()==config['selected_affinity_mask'] and k.GetPriorityClass(handle)==0x4000
    return dict(pid=os.getpid(),affinity_mask=affinity(),logical_processors=config['selected_logical_processors'],
        gurobi_threads=6,priority_class=k.GetPriorityClass(handle),priority='BELOW_NORMAL')
