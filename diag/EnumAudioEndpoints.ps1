# Read-only Core Audio endpoint diagnostic (v3 - HRESULT logged per step).
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace AudioDiag3 {

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
    public Guid fmtid;
    public int pid;
    public PropertyKey(Guid f, int p) { fmtid = f; pid = p; }
}

[StructLayout(LayoutKind.Explicit)]
public struct PropVariant {
    [FieldOffset(0)] public short vt;
    [FieldOffset(8)] public IntPtr p;
    [FieldOffset(8)] public int i;
    [FieldOffset(8)] public float f;
}

[ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioEndpointVolume {
    int RegisterControlChangeNotify(IntPtr notify);
    int UnregisterControlChangeNotify(IntPtr notify);
    int GetChannelCount(out int count);
    int SetMasterVolumeLevel(float level, ref Guid ctx);
    int SetMasterVolumeLevelScalar(float level, ref Guid ctx);
    int GetMasterVolumeLevel(out float level);
    int GetMasterVolumeLevelScalar(out float level);
    int SetChannelVolumeLevel(int ch, float level, ref Guid ctx);
    int SetChannelVolumeLevelScalar(int ch, float level, ref Guid ctx);
    int GetChannelVolumeLevel(int ch, out float level);
    int GetChannelVolumeLevelScalar(int ch, out float level);
    int SetMute(bool mute, ref Guid ctx);
    int GetMute(out bool mute);
    int GetVolumeStepInfo(out int step, out int stepCount);
    int VolumeStepUp(ref Guid ctx);
    int VolumeStepDown(ref Guid ctx);
    int QueryHardwareSupport(out int mask);
    int GetVolumeRange(out float min, out float max, out float inc);
}

public static class Diag {
    static string H(int hr) { return "0x" + hr.ToString("X8"); }
    static string PvString(PropVariant pv) {
        if (pv.vt == 31 && pv.p != IntPtr.Zero) return Marshal.PtrToStringUni(pv.p);
        return null;
    }

    public static string[] Run() {
        var L = new System.Collections.Generic.List<string>();
        try { return RunInner(L); }
        catch (Exception ex) {
            L.Add("");
            L.Add("EXCEPTION " + ex.GetType().Name + ": " + ex.Message);
            L.Add("HRESULT=0x" + ex.HResult.ToString("X8"));
            L.Add(ex.StackTrace);
            return L.ToArray();
        }
    }

    static string[] RunInner(System.Collections.Generic.List<string> L) {

        var fname = new PropertyKey(new Guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14);
        var fdesc = new PropertyKey(new Guid("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 2);
        var enh   = new PropertyKey(new Guid("1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E"), 5); // Disable_SysFx
        var excl  = new PropertyKey(new Guid("B3F8FA53-0004-438E-9003-51A46E139BFC"), 3); // ExclusiveMode (per-user)
        var prio  = new PropertyKey(new Guid("B3F8FA53-0004-438E-9003-51A46E139BFC"), 2); // exclusive priority
        var formt = new PropertyKey(new Guid("F19F064D-082C-4E27-BC73-6882A1BB8E4C"), 0); // PKEY_AudioEngine_DeviceFormat
        var mix   = new PropertyKey(new Guid("E4870E26-3CC5-4CD2-BA46-CA0A9A70ED04"), 0); // PKEY_AudioEngine_OEMFormat

        var enumr = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());

        int hr;
        IMMDeviceCollection col;
        hr = enumr.EnumAudioEndpoints(0, 1, out col);   // 1 = DEVICE_STATE_ACTIVE only (unplugged endpoints cannot be activated)
        L.Add("EnumAudioEndpoints hr=" + H(hr));
        if (col == null) { L.Add("collection NULL - abort"); return L.ToArray(); }

        int n = -1;
        hr = col.GetCount(out n);
        L.Add("count hr=" + H(hr) + " -> " + n);

        string defId = "(none)";
        IMMDevice defDev;
        int dhr = enumr.GetDefaultAudioEndpoint(0, 0, out defDev);
        L.Add("GetDefaultAudioEndpoint(eRender,eConsole) hr=" + H(dhr));
        if (defDev != null) { int ihr = defDev.GetId(out defId); L.Add("  default GetId hr=" + H(ihr)); }
        L.Add("DEFAULT = " + defId);
        L.Add("");

        for (int i = 0; i < n; i++) {
            L.Add("=== ENDPOINT " + (i + 1) + " / " + n);
            IMMDevice d;
            hr = col.Item(i, out d);
            L.Add("  Item hr=" + H(hr));
            if (d == null) { L.Add("  device NULL"); continue; }

            string id = "?"; int ihr = d.GetId(out id);
            int st = -1; int shr = d.GetState(out st);
            L.Add("  GetId hr=" + H(ihr) + "  GetState hr=" + H(shr) + " state=" + st);
            L.Add("  id=" + id);
            L.Add("  isDefault=" + (id == defId));

            IPropertyStore ps;
            int phr = d.OpenPropertyStore(0, out ps);
            L.Add("  OpenPropertyStore hr=" + H(phr));
            string name = "(unread)";
            if (ps != null) {
                var k = fname; PropVariant v;
                int ghr = ps.GetValue(ref k, out v);
                name = PvString(v);
                if (string.IsNullOrEmpty(name)) { var k2 = fdesc; PropVariant v2; ps.GetValue(ref k2, out v2); name = PvString(v2); }
                L.Add("  name='" + name + "' (GetValue hr=" + H(ghr) + ")");

                var ke = enh; PropVariant ve;
                int ehr = ps.GetValue(ref ke, out ve);
                L.Add("  Disable_SysFx(enhancements OFF if 1) hr=" + H(ehr) + " " + Fmt(ve));

                var kx = excl; PropVariant vx;
                int xhr = ps.GetValue(ref kx, out vx);
                L.Add("  ExclusiveMode(per-user; TRUE=apps may take exclusive control) hr=" + H(xhr) + " " + Fmt(vx));

                var kp = prio; PropVariant vp;
                int xp = ps.GetValue(ref kp, out vp);
                L.Add("  ExclusivePriority hr=" + H(xp) + " " + Fmt(vp));
            }

            Guid iid = typeof(IAudioEndpointVolume).GUID;
            IntPtr pv;
            int ahr = d.Activate(ref iid, 1, IntPtr.Zero, out pv);
            L.Add("  Activate(IAudioEndpointVolume) hr=" + H(ahr));
            if (ahr == 0 && pv != IntPtr.Zero) {
                var vol = (IAudioEndpointVolume)Marshal.GetObjectForIUnknown(pv);
                int ch = -1; vol.GetChannelCount(out ch);
                int hw = -1; int hhr = vol.QueryHardwareSupport(out hw);
                float m = -1; vol.GetMasterVolumeLevelScalar(out m);
                bool mu = false; vol.GetMute(out mu);
                float vmin = 0, vmax = 0, vinc = 0; vol.GetVolumeRange(out vmin, out vmax, out vinc);
                L.Add("  channels=" + ch + "  hwSupport hr=" + H(hhr) + " mask=" + hw + " => " + HwText(hw));
                L.Add("  masterVolume=" + (m * 100f).ToString("F1") + "%  muted=" + mu);
                L.Add("  range dB: min=" + vmin.ToString("F2") + " max=" + vmax.ToString("F2") + " inc=" + vinc.ToString("F3"));
                for (int c = 0; c < ch; c++) { float cv; vol.GetChannelVolumeLevelScalar(c, out cv); L.Add("    ch" + c + "=" + (cv * 100f).ToString("F1") + "%"); }
                Marshal.Release(pv);
            }
            L.Add("");
        }
        return L.ToArray();
    }

    static string Fmt(PropVariant v) {
        if (v.vt == 0) return "(default / property not set)";
        if (v.vt == 11) return (v.i != 0) ? "TRUE" : "FALSE";
        if (v.vt == 19) return v.i.ToString();
        return "vt=" + v.vt;
    }

    static string HwText(int mask) {
        string t = "";
        if ((mask & 1) != 0) t += "HARDWARE_VOLUME ";
        if ((mask & 2) != 0) t += "HARDWARE_MUTE ";
        if (t == "") t = "NONE -> software volume only (host volume can be ignored by device)";
        return t.Trim();
    }
}
}
'@

[AudioDiag3.Diag]::Run()

