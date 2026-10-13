# Read-only: read per-user exclusive-mode / enhancement switches via the property store.
# These are per-user values (not stored under HKLM MmDevices\Properties), so they must be read via API.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace AudioSwitch {

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
public class MMDeviceEnumeratorComObject { }

[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
    int GetDevice(string id, out IMMDevice device);
    int RegisterEndpointNotificationCallback(IntPtr client);
    int UnregisterEndpointNotificationCallback(IntPtr client);
}

[ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDeviceCollection {
    int GetCount(out int count);
    int Item(int index, out IMMDevice device);
}

[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IMMDevice {
    int Activate(ref Guid iid, int clsCtx, IntPtr activationParams, out IntPtr iface);
    int OpenPropertyStore(int access, out IPropertyStore store);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetState(out int state);
}

[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore {
    int GetCount(out int count);
    int GetAt(int index, out PropertyKey key);
    int GetValue(ref PropertyKey key, out PropVariant value);
    int SetValue(ref PropertyKey key, ref PropVariant value);
    int Commit();
}

[StructLayout(LayoutKind.Sequential)]
public struct PropertyKey {
    public Guid fmtid; public int pid;
    public PropertyKey(Guid f, int p) { fmtid = f; pid = p; }
}

[StructLayout(LayoutKind.Explicit)]
public struct PropVariant {
    [FieldOffset(0)] public short vt;
    [FieldOffset(8)] public IntPtr p;
    [FieldOffset(8)] public int i;
}

public static class Sw {
    static string H(int hr) { return "0x" + hr.ToString("X8"); }

    // PKEY_AudioEndpoint_* family, fmtid {1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E}
    static readonly Guid EP = new Guid("1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E");
    // PKEY_AudioEndpoint_Disable_SysFx == pid 5 ; PKEY_AudioEndpoint_Supports_EventDriven_Mode == 7
    // PKEY_Endpoint_Enable_Output_Mixformat etc. Also {B3F8FA53-...} = PKEY_AudioEndpoint_ExclusiveMode? verify by listing.

    public static string[] Run() {
        var L = new System.Collections.Generic.List<string>();
        var fname = new PropertyKey(new Guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14);

        var enumr = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        IMMDeviceCollection col;
        enumr.EnumAudioEndpoints(0, 1, out col);
        int n; col.GetCount(out n);

        for (int i = 0; i < n; i++) {
            IMMDevice d; col.Item(i, out d);
            string id; d.GetId(out id);
            IPropertyStore ps; d.OpenPropertyStore(0, out ps);
            var kf = fname; PropVariant vf; ps.GetValue(ref kf, out vf);
            string name = (vf.vt == 31 && vf.p != IntPtr.Zero) ? Marshal.PtrToStringUni(vf.p) : "?";

            L.Add("=== ACTIVE ENDPOINT " + (i + 1) + ": " + name);
            L.Add("    id=" + id);

            int cnt; ps.GetCount(out cnt);
            L.Add("    property count=" + cnt);

            // Dump every value in the {1DA5D803...} (endpoint) and {B3F8FA53...} (device/format) families,
            // plus anything numeric so we can spot the exclusive-mode flag.
            for (int j = 0; j < cnt; j++) {
                PropertyKey k; ps.GetAt(j, out k);
                string fam = k.fmtid.ToString().ToUpper();
                if (fam == "1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E" || fam == "B3F8FA53-0004-438E-9003-51A46E139BFC") {
                    PropVariant v;
                    int hr = ps.GetValue(ref k, out v);
                    string val;
                    if (v.vt == 0) val = "(not set / default)";
                    else if (v.vt == 11) val = (v.i != 0) ? "TRUE" : "FALSE";
                    else if (v.vt == 19) val = v.i.ToString();
                    else val = "vt=" + v.vt;
                    L.Add("      " + fam.Substring(0, 8) + " pid=" + k.pid + "  " + val + "   (hr=" + H(hr) + ")");
                }
            }
            L.Add("");
        }
        return L.ToArray();
    }
}
}
'@

[AudioSwitch.Sw]::Run()
