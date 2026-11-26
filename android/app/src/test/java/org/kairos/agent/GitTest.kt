// SPDX-License-Identifier: GPL-3.0-or-later
// Ported from tests/test_git_tool.py (system git CLI) to the JGit-based GitTool, plus push/pull
// against a local bare remote and agent-tool gating.
package org.kairos.agent

import kotlinx.coroutines.runBlocking
import org.eclipse.jgit.api.Git
import org.junit.Assert.*
import org.junit.Test
import org.kairos.agent.agent.*
import org.kairos.agent.git.*
import java.io.File
import java.nio.file.Files

class GitTest {
    private fun tmp(): File = Files.createTempDirectory("kgit").toFile()
    private fun cfg(extra: GitConfig.() -> GitConfig = { this }) = GitConfig(enabled = true, authorName = "Test", authorEmail = "t@t.io").extra()

    private fun tool(root: File, c: GitConfig = cfg(), repo: String = "work"): GitTool {
        val t = GitTool(root) { c.copy(activeRepo = repo) }
        return t
    }

    @Test fun nameValidation() {
        assertEquals("feature/x", checkName("feature/x"))
        for (bad in listOf("../bad", "-rf", "/abs", "a b", "")) assertThrows(IllegalArgumentException::class.java) { checkName(bad) }
        assertEquals("HEAD~1", checkRef("HEAD~1"))
        assertThrows(IllegalArgumentException::class.java) { checkRef("--output=/x") }
    }

    @Test fun confine() {
        val root = tmp()
        val t = GitTool(root) { cfg() }
        assertThrows(SecurityException::class.java) { t.confine(root.parentFile.path) }
        assertThrows(SecurityException::class.java) { t.confine("../outside") }
        assertEquals(File(root, "ok").canonicalFile, t.confine("ok"))
    }

    @Test fun gitWorkflow() {
        val root = tmp(); val t = tool(root)
        t.init()
        assertTrue(t.isRepo())
        File(root, "work/a.txt").writeText("hello")
        assertTrue(t.status().contains("?? a.txt"))
        assertEquals("(no commits)", t.log(5))
        t.add()
        assertTrue(t.status().contains("A  a.txt"))
        assertTrue(t.commit("initial commit").contains("initial commit"))
        assertTrue(t.log(5).contains("initial commit"))
        assertTrue(t.log(5).contains("Test"))
        val base = t.currentBranch()
        assertEquals("main", base)
        t.createBranch("feature/x")
        assertEquals("feature/x", t.currentBranch())
        assertTrue(t.branches().contains("* feature/x"))
        t.checkout(base)
        assertEquals(base, t.currentBranch())
        File(root, "work/a.txt").writeText("hello world")
        assertTrue(t.status().contains(" M a.txt"))
        assertTrue(t.diff().contains("+hello world"))
        t.commit("second", addAll = true)
        assertTrue(t.diff(ref = "HEAD~1").let { it.contains("-hello") || it == "(no differences)" })
        assertTrue(t.status().contains("(clean working tree)"))
        assertThrows(IllegalArgumentException::class.java) { t.commit("  ") }
        File(root, "work/b.txt").writeText("tmp"); t.add()
        assertTrue(t.stash().startsWith("Saved"))
        assertTrue(t.status().contains("(clean working tree)"))
    }

    @Test fun pushPullGated() {
        val root = tmp(); val t = tool(root); t.init()
        assertThrows(SecurityException::class.java) { t.push() }
        assertThrows(SecurityException::class.java) { t.pull() }
        assertThrows(SecurityException::class.java) { t.clone("https://example.org/x.git", "x") }
    }

    @Test fun disabled() {
        val root = tmp(); val t = GitTool(root) { GitConfig(enabled = false) }
        assertThrows(SecurityException::class.java) { t.status() }
        assertThrows(SecurityException::class.java) { t.init("x") }
    }

    @Test fun summary() {
        val root = tmp(); val t = tool(root)
        assertTrue(t.summary().startsWith("Not a git repository"))
        t.init()
        assertTrue(t.summary().contains("Branch:"))
    }

    @Test fun pushAndFastForwardPullWithLocalRemote() {
        val root = tmp()
        val bare = File(tmp(), "remote.git")
        Git.init().setBare(true).setDirectory(bare).setInitialBranch("main").call().close()
        val c = cfg { copy(allowPush = true, allowPull = true) }
        val a = tool(root, c, "a"); a.init()
        Git.open(File(root, "a")).use { g -> g.remoteAdd().setName("origin").setUri(org.eclipse.jgit.transport.URIish(bare.toURI().toURL())).call() }
        File(root, "a/f.txt").writeText("1"); a.commit("one", addAll = true)
        assertTrue(a.push().contains("OK"))
        // Second clone (local URI used directly through JGit; GitTool.clone only accepts https).
        Git.cloneRepository().setURI(bare.toURI().toString()).setDirectory(File(root, "b")).call().close()
        val b = tool(root, c, "b")
        File(root, "a/f.txt").writeText("2"); a.commit("two", addAll = true); a.push()
        assertTrue(b.pull().startsWith("Pulled"))
        assertTrue(b.log(5).contains("two"))
        // Diverged history is refused, never force-pushed.
        File(root, "b/f.txt").writeText("b"); b.commit("b-side", addAll = true); b.push()
        File(root, "a/f.txt").writeText("a"); a.commit("a-side", addAll = true)
        assertThrows(GitError::class.java) { a.push() }
        assertThrows(GitError::class.java) { a.pull() }
    }

    @Test fun gitToolsGating() = runBlocking {
        val root = tmp(); val t = tool(root); t.init()
        val pack = CharacterRegistry.parsePack(File("src/main/assets/characters.json").readText())
        val reg = CharacterRegistry(pack, listOf(pack.presets[0].copy(id = "nogit", capabilities = listOf("memory"))))
        val tools = GitTools(reg, t)
        assertTrue(tools.run(ToolCall("git_status")).contains("clean working tree"))
        File(root, "work/z.txt").writeText("z")
        assertTrue(tools.run(ToolCall("git_commit", mapOf("message" to "via tool"))).contains("via tool"))
        assertTrue(tools.run(ToolCall("git_push")).startsWith("(git error"))
        reg.activeId = "nogit"
        assertEquals("(tool not permitted: git_ops)", tools.run(ToolCall("git_log")))
        assertEquals("(unknown tool: nope)", GitTools(reg, t).run(ToolCall("nope")))
    }
}
