# DECISIVE TEST - writes only the default endpoint's master volume, then restores it.
#   1. read original volume/mute
#   2. set 100%, play a quiet 440 Hz tone, sample the endpoint peak meter
#   3. set  30%, play the same tone, sample the peak meter
#   4. set  10%, play the same tone, sample the peak meter
#   5. restore original volume/mute
# Peak ratio ~= volume ratio  => the device honours host volume (a gain-based limiter works).
# Peak barely changes         => the device ignores host volume (Sound Lock's documented
#                                failure mode); only an in-path DSP limiter can help.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace VolTest {

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

[ComImport, Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IAudioMeterInformation {
    int GetPeakValue(out float peak);
    int GetMeteringChannelCount(out int channelCount);
    int GetChannelsPeakValues(int channelCount, [Out] float[] peakValues);
    int QueryHardwareSupport(out int hardwareSupportMask);
}

public static class VT {

    // ---- minimal winmm waveOut player (no managed audio player needed) ----
    [DllImport("winmm.dll")] static extern int waveOutOpen(out IntPtr h, int dev, ref WAVEFORMATEX fmt, IntPtr cb, IntPtr inst, int flags);
    [DllImport("winmm.dll")] static extern int waveOutPrepareHeader(IntPtr h, IntPtr hdr, int size);
    [DllImport("winmm.dll")] static extern int waveOutWrite(IntPtr h, IntPtr hdr, int size);
    [DllImport("winmm.dll")] static extern int waveOutReset(IntPtr h);
    [DllImport("winmm.dll")] static extern int waveOutClose(IntPtr h);

    [StructLayout(LayoutKind.Sequential)]
    struct WAVEFORMATEX { public short wFormatTag, nChannels; public int nSamplesPerSec, nAvgBytesPerSec; public short nBlockAlign, wBitsPerSample, cbSize; }

    [StructLayout(LayoutKind.Sequential)]
    struct WAVEHDR { public IntPtr lpData; public int dwBufferLength, dwBytesRecorded; public IntPtr dwUser; public int dwFlags, dwLoops; public IntPtr lpNext, reserved; }

    static void PlayTone(short[] samples, int sampleRate) {
        IntPtr h;
        var fmt = new WAVEFORMATEX();
        fmt.wFormatTag = 1; fmt.nChannels = 1; fmt.nSamplesPerSec = sampleRate;
        fmt.wBitsPerSample = 16; fmt.nBlockAlign = 2; fmt.nAvgBytesPerSec = sampleRate * 2; fmt.cbSize = 0;
        if (waveOutOpen(out h, -1, ref fmt, IntPtr.Zero, IntPtr.Zero, 0) != 0) return;

        int bytes = samples.Length * 2;
        IntPtr buf = Marshal.AllocHGlobal(bytes);
        Marshal.Copy(samples, 0, buf, samples.Length);
        IntPtr hdr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WAVEHDR)));
        var wh = new WAVEHDR();
        wh.lpData = buf; wh.dwBufferLength = bytes;
        Marshal.StructureToPtr(wh, hdr, false);

        waveOutPrepareHeader(h, hdr, Marshal.SizeOf(typeof(WAVEHDR)));
        waveOutWrite(h, hdr, Marshal.SizeOf(typeof(WAVEHDR)));
        System.Threading.Thread.Sleep(200);
        waveOutReset(h);
        waveOutClose(h);
        Marshal.FreeHGlobal(buf);
        Marshal.FreeHGlobal(hdr);
    }

    static short[] BuildTone(int ms, int rate, double freq, double amp) {
        int n = rate * ms / 1000;
        var s = new short[n];
        for (int i = 0; i < n; i++) {
            double env = Math.Min(1.0, Math.Min(i / (rate * 0.02), (n - i) / (rate * 0.02))); // 20 ms fades
            s[i] = (short)(32767 * amp * env * Math.Sin(2 * Math.PI * freq * i / rate));
        }
        return s;
    }

    public static string[] Run() {
        var L = new System.Collections.Generic.List<string>();
        int rate = 48000;
        double amp = 0.10;   // -20 dBFS : quiet but well above the meter floor
        short[] tone = BuildTone(700, rate, 440.0, amp);

        var enumr = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
        IMMDevice dev; enumr.GetDefaultAudioEndpoint(0, 0, out dev);
        string id; dev.GetId(out id);
        L.Add("ENDPOINT = " + id);

        Guid vi = typeof(IAudioEndpointVolume).GUID;
        IntPtr vp; dev.Activate(ref vi, 1, IntPtr.Zero, out vp);
        var vol = (IAudioEndpointVolume)Marshal.GetObjectForIUnknown(vp);

        float original; vol.GetMasterVolumeLevelScalar(out original);
        bool origMute; vol.GetMute(out origMute);
        int hw; vol.QueryHardwareSupport(out hw);
        L.Add("original volume = " + (original * 100f).ToString("F1") + "%  muted=" + origMute + "  hwMask=" + hw);

        Guid mi = typeof(IAudioMeterInformation).GUID;
        IntPtr mp; dev.Activate(ref mi, 1, IntPtr.Zero, out mp);
        var meter = (IAudioMeterInformation)Marshal.GetObjectForIUnknown(mp);

        var ctx = Guid.NewGuid();
        float p100, p30, p10;

        try {
            vol.SetMute(false, ref ctx);
            vol.SetMasterVolumeLevelScalar(1.00f, ref ctx);
            System.Threading.Thread.Sleep(500);
            p100 = PlayAndMeasure(tone, rate, meter);
            L.Add("pass A @ 100% : peak = " + p100.ToString("F6"));

            vol.SetMasterVolumeLevelScalar(0.30f, ref ctx);
            System.Threading.Thread.Sleep(500);
            p30 = PlayAndMeasure(tone, rate, meter);
            L.Add("pass B @  30% : peak = " + p30.ToString("F6"));

            vol.SetMasterVolumeLevelScalar(0.10f, ref ctx);
            System.Threading.Thread.Sleep(500);
            p10 = PlayAndMeasure(tone, rate, meter);
            L.Add("pass C @  10% : peak = " + p10.ToString("F6"));
        }
        finally {
            vol.SetMasterVolumeLevelScalar(original, ref ctx);
            vol.SetMute(origMute, ref ctx);
            float back; vol.GetMasterVolumeLevelScalar(out back);
            L.Add("RESTORED volume = " + (back * 100f).ToString("F1") + "%");
        }

        L.Add("");
        if (p100 > 0.0005f) {
            L.Add("ratio 30% / 100% = " + (p30 / p100).ToString("F3") + "    (expect ~0.30 if host volume is honoured)");
            L.Add("ratio 10% / 100% = " + (p10 / p100).ToString("F3") + "    (expect ~0.10 if host volume is honoured)");
            L.Add("");
            if (p30 / p100 > 0.20f && p30 / p100 < 0.45f && p10 / p100 > 0.05f && p10 / p100 < 0.18f)
                L.Add("VERDICT: device HONOURS host volume -> gain-based limiting is viable on this endpoint.");
            else if (p30 / p100 > 0.8f)
                L.Add("VERDICT: device IGNORES host volume (peak barely moved) -> only an in-path DSP limiter can cap loudness.");
            else
                L.Add("VERDICT: partial / non-linear response - inspect ratios (Bluetooth AVRCP absolute volume may quantise).");
        } else {
            L.Add("VERDICT: no signal detected at 100% - the tone did not reach the meter; result inconclusive.");
        }
        return L.ToArray();
    }

    static float PlayAndMeasure(short[] tone, int rate, IAudioMeterInformation meter) {
        float best = 0f, last = 0f;
        var t = new System.Threading.Thread(() => PlayTone(tone, rate));
        t.Start();
        var t0 = DateTime.UtcNow;
        while (t.IsAlive || (DateTime.UtcNow - t0).TotalMilliseconds < 900) {
            float p; meter.GetPeakValue(out p);
            if (p > best) best = p;
            last = p;
            System.Threading.Thread.Sleep(5);
        }
        t.Join();
        System.Threading.Thread.Sleep(250);
        return best;
    }
}
}
'@

[VolTest.VT]::Run()
