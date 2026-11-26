// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Port of kairos/git_tool.py using JGit (EDL-1.0) instead of
// the system `git` CLI. Repositories are confined to the app's repo root; push/pull are opt-in and
// force operations are never offered (same policy as desktop).
package org.kairos.agent.git

import org.eclipse.jgit.api.Git
import org.eclipse.jgit.api.ListBranchCommand
import org.eclipse.jgit.api.MergeCommand
import org.eclipse.jgit.api.errors.GitAPIException
import org.eclipse.jgit.api.errors.NoHeadException
import org.eclipse.jgit.lib.PersonIdent
import org.eclipse.jgit.lib.Repository
import org.eclipse.jgit.storage.file.FileRepositoryBuilder
import org.eclipse.jgit.transport.UsernamePasswordCredentialsProvider
import org.eclipse.jgit.treewalk.CanonicalTreeParser
import java.io.ByteArrayOutputStream
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale

data class GitConfig(
    val enabled: Boolean = false,
    val allowPush: Boolean = false,
    val allowPull: Boolean = false,
    val authorName: String = "",
    val authorEmail: String = "",
    val token: String? = null,
    /** Repository (sub-folder of the repo root) used when none is given; blank = the root itself. */
    val activeRepo: String = "",
)

class GitError(msg: String) : RuntimeException(msg)

private val NAME_RE = Regex("^[A-Za-z0-9._/\\-]{1,120}$")
private val REF_RE = Regex("^[A-Za-z0-9._/~^@{}\\-]{1,200}$")

fun checkName(name: String?): String {
    val n = (name ?: "").trim()
    if (!NAME_RE.matches(n) || ".." in n || n.startsWith("/") || n.startsWith("\\") || n.startsWith("-"))
        throw IllegalArgumentException("Invalid branch/remote name.")
    return n
}

fun checkRef(ref: String?): String {
    val r = (ref ?: "").trim()
    if (!REF_RE.matches(r) || r.startsWith("-")) throw IllegalArgumentException("Invalid git ref.")
    return r
}

class GitTool(val root: File, private val cfg: () -> GitConfig) {
    init { root.mkdirs() }

    private fun requireEnabled() { if (!cfg().enabled) throw SecurityException("Git integration is disabled (enable it in the Git screen).") }

    /** Resolve [repo] (a folder name under the root, or a path inside it) and keep it inside the root. */
    fun confine(repo: String? = null): File {
        val base = root.canonicalFile
        val name = (repo ?: cfg().activeRepo).trim()
        val target = (if (name.isEmpty()) base else if (File(name).isAbsolute) File(name) else File(base, name)).canonicalFile
        if (target != base && !target.path.startsWith(base.path + File.separator))
            throw SecurityException("Repository is outside the allowed git root.")
        return target
    }

    private inline fun <T> withGit(repo: String?, block: (Git) -> T): T {
        val dir = confine(repo)
        val r: Repository = try {
            FileRepositoryBuilder().setWorkTree(dir).setGitDir(File(dir, ".git")).setMustExist(true).build()
        } catch (e: Exception) { throw GitError("Not a git repository: ${dir.name}") }
        return try { Git(r).use(block) } catch (e: GitAPIException) { throw GitError(e.message ?: e.javaClass.simpleName) }
        finally { r.close() }
    }

    private fun author(): PersonIdent {
        val c = cfg()
        return PersonIdent(c.authorName.ifBlank { "KAIROS" }, c.authorEmail.ifBlank { "kairos@localhost" })
    }

    private fun creds() = cfg().token?.takeIf { it.isNotBlank() }?.let { UsernamePasswordCredentialsProvider("x-access-token", it) }

    // ---- Read operations ----
    fun isRepo(repo: String? = null): Boolean = try { File(confine(repo), ".git").isDirectory } catch (e: Exception) { false }

    fun currentBranch(repo: String? = null): String = withGit(repo) { it.repository.branch ?: "HEAD" }

    fun status(repo: String? = null): String { requireEnabled(); return withGit(repo) { g ->
        val s = g.status().call()
        val lines = mutableListOf("## ${g.repository.branch}")
        s.added.sorted().forEach { lines += "A  $it" }
        s.changed.sorted().forEach { lines += "M  $it" }
        s.removed.sorted().forEach { lines += "D  $it" }
        s.modified.sorted().forEach { lines += " M $it" }
        s.missing.sorted().forEach { lines += " D $it" }
        s.conflicting.sorted().forEach { lines += "UU $it" }
        s.untracked.sorted().forEach { lines += "?? $it" }
        if (lines.size == 1) "${lines[0]}\n(clean working tree)" else lines.joinToString("\n")
    } }

    fun diff(staged: Boolean = false, ref: String? = null, repo: String? = null): String { requireEnabled(); return withGit(repo) { g ->
        val out = ByteArrayOutputStream()
        val cmd = g.diff().setOutputStream(out).setCached(staged)
        if (!ref.isNullOrBlank()) {
            val id = g.repository.resolve(checkRef(ref) + "^{tree}") ?: throw GitError("Unknown ref '$ref'.")
            cmd.setOldTree(CanonicalTreeParser().apply { g.repository.newObjectReader().use { reset(it, id) } })
        }
        cmd.call()
        out.toString(Charsets.UTF_8.name()).take(20000).ifBlank { "(no differences)" }
    } }

    fun log(n: Int = 20, repo: String? = null): String { requireEnabled(); return withGit(repo) { g ->
        val fmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)
        try {
            g.log().setMaxCount(n.coerceIn(1, 200)).call().joinToString("\n") { c ->
                "${c.id.abbreviate(7).name()}  ${fmt.format(c.authorIdent.`when`)}  ${c.authorIdent.name}  ${c.shortMessage}"
            }.ifBlank { "(no commits)" }
        } catch (e: NoHeadException) { "(no commits)" }
    } }

    fun branches(repo: String? = null): String { requireEnabled(); return withGit(repo) { g ->
        val cur = g.repository.fullBranch
        g.branchList().setListMode(ListBranchCommand.ListMode.ALL).call().joinToString("\n") { r ->
            (if (r.name == cur) "* " else "  ") + r.name.removePrefix("refs/heads/").replaceFirst("refs/remotes/", "remotes/")
        }.ifBlank { "(no branches)" }
    } }

    fun remotes(repo: String? = null): String { requireEnabled(); return withGit(repo) { g ->
        g.remoteList().call().flatMap { rc -> rc.urIs.flatMap { u -> listOf("${rc.name}\t$u (fetch)", "${rc.name}\t$u (push)") } }
            .joinToString("\n").ifBlank { "(no remotes)" }
    } }

    // ---- Mutations ----
    fun init(repo: String? = null): String {
        requireEnabled()
        val dir = confine(repo).also { it.mkdirs() }
        try { Git.init().setDirectory(dir).setInitialBranch("main").call().close() } catch (e: GitAPIException) { throw GitError(e.message ?: "init failed") }
        return "Initialized empty Git repository in ${dir.name}"
    }

    fun clone(url: String, name: String): String {
        requireEnabled()
        if (!cfg().allowPull) throw SecurityException("Git pull/clone is disabled (allow pull in the Git screen).")
        if (!url.startsWith("https://")) throw IllegalArgumentException("Only https:// remotes are supported.")
        val dir = confine(checkName(name))
        if (dir.exists() && (dir.list()?.isNotEmpty() == true)) throw GitError("Folder '$name' already exists.")
        try { Git.cloneRepository().setURI(url).setDirectory(dir).setCredentialsProvider(creds()).call().close() }
        catch (e: GitAPIException) { throw GitError(e.message ?: "clone failed") }
        return "Cloned into $name"
    }

    fun createBranch(name: String, checkout: Boolean = true, repo: String? = null): String { requireEnabled(); val n = checkName(name); return withGit(repo) { g ->
        if (checkout) { g.checkout().setCreateBranch(true).setName(n).call(); "Switched to a new branch '$n'" }
        else { g.branchCreate().setName(n).call(); "Created branch $n" }
    } }

    fun checkout(name: String, repo: String? = null): String { requireEnabled(); val n = checkName(name); return withGit(repo) { g ->
        g.checkout().setName(n).call(); "Switched to branch '$n'"
    } }

    fun add(paths: List<String>? = null, repo: String? = null): String { requireEnabled(); return withGit(repo) { g ->
        if (paths.isNullOrEmpty()) { g.add().addFilepattern(".").call(); g.add().setUpdate(true).addFilepattern(".").call() }
        else { val a = g.add(); paths.forEach { a.addFilepattern(it) }; a.call() }
        "staged"
    } }

    fun commit(message: String, addAll: Boolean = false, repo: String? = null): String {
        requireEnabled()
        val msg = message.trim()
        if (msg.isEmpty()) throw IllegalArgumentException("Commit message is required.")
        if (addAll) add(null, repo)
        return withGit(repo) { g ->
            val c = g.commit().setMessage(msg).setAuthor(author()).setCommitter(author()).call()
            "[${g.repository.branch} ${c.id.abbreviate(7).name()}] ${c.shortMessage}"
        }
    }

    fun stash(repo: String? = null): String { requireEnabled(); return withGit(repo) { g ->
        g.stashCreate().setPerson(author()).call()?.let { "Saved working directory (${it.id.abbreviate(7).name()})" } ?: "No local changes to save"
    } }

    fun pull(repo: String? = null): String {
        requireEnabled()
        if (!cfg().allowPull) throw SecurityException("Git pull is disabled (allow pull in the Git screen).")
        return withGit(repo) { g ->
            val r = g.pull().setFastForward(MergeCommand.FastForwardMode.FF_ONLY).setCredentialsProvider(creds()).call()
            if (!r.isSuccessful) throw GitError("Pull failed (not a fast-forward?): ${r.mergeResult?.mergeStatus ?: r.fetchResult?.messages}")
            "Pulled: ${r.mergeResult?.mergeStatus ?: "up to date"}"
        }
    }

    fun push(remote: String = "origin", branch: String? = null, repo: String? = null): String {
        requireEnabled()
        if (!cfg().allowPush) throw SecurityException("Git push is disabled (allow push in the Git screen).")
        val rem = checkName(remote.ifBlank { "origin" })
        return withGit(repo) { g ->
            val b = branch?.let { checkName(it) } ?: g.repository.branch
            // Never force: setForce(false) is explicit and no force option is exposed.
            val res = g.push().setRemote(rem).add(b).setForce(false).setCredentialsProvider(creds()).call()
            res.flatMap { it.remoteUpdates }.joinToString("\n") { "${it.remoteName}: ${it.status}${it.message?.let { m -> " ($m)" } ?: ""}" }
                .also { s -> if ("REJECTED" in s) throw GitError("Push rejected: $s") }
                .ifBlank { "Pushed." }
        }
    }

    /** Compact human-readable summary for the UI/Telegram (desktop summary()). */
    fun summary(repo: String? = null): String {
        try { confine(repo) } catch (e: SecurityException) { return e.message.orEmpty() }
        if (!isRepo(repo)) return "Not a git repository (init or clone one in the Git screen)."
        val parts = mutableListOf<String>()
        parts += try { "Branch: ${currentBranch(repo)}" } catch (e: Exception) { "Branch: (error: ${e.message})" }
        parts += try { "Status:\n" + status(repo) } catch (e: Exception) { "Status: (error: ${e.message})" }
        return parts.joinToString("\n")
    }
}
