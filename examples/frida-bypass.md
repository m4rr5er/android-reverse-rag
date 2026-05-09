# Frida 检测与绕过

## TracerPid 检测

Android 反调试代码经常读取 `/proc/self/status` 并检查 `TracerPid`。如果该值不为 0，说明进程可能正在被调试或被注入。

Frida bypass 可以 hook `open`, `read`, `fgets`，在返回内容里把 `TracerPid` 改成 0。

## JNI_OnLoad 与 RegisterNatives

Native 层常在 `JNI_OnLoad` 中调用 `RegisterNatives` 动态注册 Java native 方法。逆向时可以在 `RegisterNatives` 下断点，打印类名、方法名、签名和函数地址。

