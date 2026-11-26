// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. JGit reads ~/.gitconfig and may try to run a system `git`
// to locate /etc/gitconfig. Android has neither, so point every config at app-private files.
package org.kairos.agent.git

import org.eclipse.jgit.lib.Config
import org.eclipse.jgit.storage.file.FileBasedConfig
import org.eclipse.jgit.util.FS
import org.eclipse.jgit.util.SystemReader
import java.io.File

class AndroidSystemReader(private val home: File, private val base: SystemReader = SystemReader.getInstance()) : SystemReader() {
    init { home.mkdirs() }
    override fun getHostname(): String = "android"
    override fun getenv(variable: String?): String? = when (variable) {
        "GIT_CONFIG_NOSYSTEM" -> "true"
        "HOME" -> home.path
        else -> base.getenv(variable)
    }
    override fun getProperty(key: String?): String? = if (key == "user.home") home.path else base.getProperty(key)
    override fun openUserConfig(parent: Config?, fs: FS?): FileBasedConfig = FileBasedConfig(parent, File(home, ".gitconfig"), fs)
    override fun openSystemConfig(parent: Config?, fs: FS?): FileBasedConfig =
        object : FileBasedConfig(parent, File(home, ".gitconfig-system"), fs) {
            override fun load() = Unit
            override fun isOutdated() = false
        }
    override fun openJGitConfig(parent: Config?, fs: FS?): FileBasedConfig = FileBasedConfig(parent, File(home, ".jgitconfig"), fs)
    override fun getCurrentTime(): Long = System.currentTimeMillis()
    override fun getTimezone(`when`: Long): Int = java.util.TimeZone.getDefault().getOffset(`when`) / 60000

    companion object {
        fun install(home: File) { SystemReader.setInstance(AndroidSystemReader(home)) }
    }
}
