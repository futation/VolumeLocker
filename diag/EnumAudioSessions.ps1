# Read-only Core Audio session + endpoint peak-meter diagnostic.
# Lists active audio sessions: owning process, session volume, peak meter, channel count.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace AudioSess {

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
    int OpenPropertyStore(int access, out IntPtr store);
    int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetState(out int state);
}

[ComImport, Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioSessionManager2 {
    // IAudioSessionManager
    int GetAudioSessionControl(IntPtr sessionGuid, int streamFlags, out IntPtr sessionControl);
    int GetSimpleAudioVolume(IntPtr sessionGuid, int streamFlags, out IntPtr audioVolume);
    // IAudioSessionManager2
    int GetSessionEnumerator(out IAudioSessionEnumerator sessionEnum);
    int RegisterSessionNotification(IntPtr sessionNotification);
    int UnregisterSessionNotification(IntPtr sessionNotification);
    int RegisterDuckNotification(string sessionId, IntPtr duckNotification);
    int UnregisterDuckNotification(IntPtr duckNotification);
}

[ComImport, Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioSessionEnumerator {
    int GetCount(out int sessionCount);
    int GetSession(int sessionCount, out IAudioSessionControl session);
}

[ComImport, Guid("F4B1A599-7266-4319-A8CA-E70ACB11E8CD"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioSessionControl {
    int GetState(out int state);
    int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);
    int SetDisplayName(string name, IntPtr eventContext);
    int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path);
    int SetIconPath(string path, IntPtr eventContext);
    int GetGroupingParam(out Guid groupingParam);
    int SetGroupingParam(ref Guid groupingParam, IntPtr eventContext);
    int RegisterAudioSessionNotification(IntPtr newNotifications);
    int UnregisterAudioSessionNotification(IntPtr newNotifications);
}

[ComImport, Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioSessionControl2 {
    // IAudioSessionControl
    int GetState(out int state);
    int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);
    int SetDisplayName(string name, IntPtr eventContext);
    int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path);
    int SetIconPath(string path, IntPtr eventContext);
    int GetGroupingParam(out Guid groupingParam);
    int SetGroupingParam(ref Guid groupingParam, IntPtr eventContext);
    int RegisterAudioSessionNotification(IntPtr newNotifications);
    int UnregisterAudioSessionNotification(IntPtr newNotifications);
    // IAudioSessionControl2
    int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
    int GetProcessId(out int pid);
    int IsSystemSoundsSession();
    int SetDuckingPreference(bool optOut);
}

[ComImport, Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface ISimpleAudioVolume {
    int SetMasterVolume(float level, ref Guid eventContext);
    int GetMasterVolume(out float level);
    int SetMute(bool mute, ref Guid eventContext);
    int GetMute(out bool mute);
}

[ComImport, Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioMeterInformation {
    int GetPeakValue(out float peak);
    int GetMeteringChannelCount(out int channelCount);
    int GetChannelsPeakValues(int channelCount, [Out] float[] peakValues);
    int QueryHardwareSupport(out int hardwareSupportMask);
}

public static class Sess {
    public static string[] Run() {
        var lines = new System.Collections.Generic.List<string>();
        var enumr = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());

        IMMDevice dev;
        enumr.GetDefaultAudioEndpoint(0, 0, out dev);
        string devId; dev.GetId(out devId);
        lines.Add("DEFAULT RENDER ENDPOINT: " + devId);

        // Endpoint-level meter (whole device mix).
        Guid mk = typeof(IAudioMeterInformation).GUID;
        IntPtr mp;
        int hr = dev.Activate(ref mk, 23, IntPtr.Zero, out mp);
        if (hr == 0 && mp != IntPtr.Zero) {
            var em = (IAudioMeterInformation)Marshal.GetObjectForIUnknown(mp);
            float p; int cc;
            em.GetPeakValue(out p);
            int hrc = em.GetMeteringChannelCount(out cc);
            lines.Add("ENDPOINT peak = " + p.ToString("F6") + "   meteringChannels=" + cc + " (hr=0x" + hrc.ToString("X8") + ")");
            Marshal.Release(mp);
        } else {
            lines.Add("ENDPOINT meter activate FAILED hr=0x" + hr.ToString("X8"));
        }

        Guid sm = typeof(IAudioSessionManager2).GUID;
        IntPtr sp;
        dev.Activate(ref sm, 23, IntPtr.Zero, out sp);
        var mgr = (IAudioSessionManager2)Marshal.GetObjectForIUnknown(sp);

        IAudioSessionEnumerator senum;
        mgr.GetSessionEnumerator(out senum);
        int count; senum.GetCount(out count);
        lines.Add("");
        lines.Add("AUDIO SESSIONS: " + count);

        for (int i = 0; i < count; i++) {
            IAudioSessionControl sc;
            senum.GetSession(i, out sc);
            var sc2 = (IAudioSessionControl2)sc;

            int state; sc.GetState(out state);
            int pid = -1; sc2.GetProcessId(out pid);
            string disp = ""; sc.GetDisplayName(out disp);

            string procName = "";
            try { procName = System.Diagnostics.Process.GetProcessById(pid).ProcessName; } catch { procName = "(pid gone)"; }

            string sysSnd = sc2.IsSystemSoundsSession() == 0 ? "SYSTEM-SOUNDS" : "";
            string st = state == 0 ? "INACTIVE" : (state == 1 ? "ACTIVE" : "EXPIRED");

            var sv = (ISimpleAudioVolume)sc;
            float vol = -1; sv.GetMasterVolume(out vol);
            bool muted = false; sv.GetMute(out muted);

            var meter = (IAudioMeterInformation)sc;
            float peak = -1; meter.GetPeakValue(out peak);
            int mcc = -1; meter.GetMeteringChannelCount(out mcc);

            lines.Add("");
            lines.Add("--- SESSION " + (i + 1) + " : " + procName + " [pid " + pid + "] " + sysSnd);
            lines.Add("    state      = " + st);
            lines.Add("    volume     = " + (vol * 100f).ToString("F1") + "%  muted=" + muted);
            lines.Add("    peak       = " + peak.ToString("F6") + "   meteringChannels=" + mcc);
            if (!string.IsNullOrEmpty(disp)) lines.Add("    display    = " + disp);
            string sid = "";
            if (sc2.GetSessionIdentifier(out sid) == 0 && !string.IsNullOrEmpty(sid))
                lines.Add("    sessionId  = " + sid);
        }
        Marshal.Release(sp);
        return lines.ToArray();
    }
}
}
'@

[AudioSess.Sess]::Run()
