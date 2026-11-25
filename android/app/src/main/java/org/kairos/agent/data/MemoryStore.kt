// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Chat history + retained memory (desktop: knowledge.py remember/recall).
package org.kairos.agent.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

data class StoredMessage(val id: Long, val role: String, val content: String, val ts: Long)
data class Memory(val id: Long, val content: String, val ts: Long)
data class LibraryDoc(val id: String, val url: String, val title: String, val summary: String, val ts: Long)

class MemoryStore(context: Context, name: String? = "kairos.db") :
    SQLiteOpenHelper(context, name, null, 2) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, ts INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE memories(id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL UNIQUE, ts INTEGER NOT NULL)")
        createLibrary(db)
    }

    // Desktop storage/knowledge.py "documents" table (the knowledge library).
    private fun createLibrary(db: SQLiteDatabase) =
        db.execSQL("CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, url TEXT, title TEXT, raw_html TEXT, cleaned_text TEXT, summary TEXT, ts INTEGER NOT NULL)")

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) createLibrary(db)
    }

    fun addMessage(role: String, content: String): Long = writableDatabase.insert("messages", null,
        ContentValues().apply { put("role", role); put("content", content); put("ts", System.currentTimeMillis()) })

    fun recentMessages(limit: Int = 50): List<StoredMessage> =
        readableDatabase.rawQuery(
            "SELECT id, role, content, ts FROM (SELECT * FROM messages ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
            arrayOf(limit.toString())
        ).use { c -> buildList { while (c.moveToNext()) add(StoredMessage(c.getLong(0), c.getString(1), c.getString(2), c.getLong(3))) } }

    fun clearMessages() { writableDatabase.delete("messages", null, null) }

    fun remember(content: String): Boolean {
        val text = content.trim()
        if (text.isEmpty()) return false
        return writableDatabase.insertWithOnConflict("memories", null,
            ContentValues().apply { put("content", text); put("ts", System.currentTimeMillis()) },
            SQLiteDatabase.CONFLICT_IGNORE) != -1L
    }

    /** Keyword recall: rank memories by how many query terms they contain. */
    fun recall(query: String, limit: Int = 8): List<Memory> {
        val terms = query.lowercase().split(Regex("\\W+")).filter { it.length > 2 }.distinct()
        val all = allMemories()
        if (terms.isEmpty()) return all.take(limit)
        return all.map { m -> m to terms.count { m.content.lowercase().contains(it) } }
            .filter { it.second > 0 }
            .sortedWith(compareByDescending<Pair<Memory, Int>> { it.second }.thenByDescending { it.first.ts })
            .take(limit).map { it.first }
    }

    fun allMemories(): List<Memory> =
        readableDatabase.rawQuery("SELECT id, content, ts FROM memories ORDER BY id DESC", null)
            .use { c -> buildList { while (c.moveToNext()) add(Memory(c.getLong(0), c.getString(1), c.getLong(2))) } }

    fun forget(id: Long) { writableDatabase.delete("memories", "id=?", arrayOf(id.toString())) }

    // ---- Knowledge library ----
    fun addDocument(url: String, title: String, rawHtml: String, cleaned: String, summary: String,
                    id: String = java.util.UUID.randomUUID().toString().replace("-", "")): String {
        writableDatabase.insertWithOnConflict("documents", null, ContentValues().apply {
            put("id", id); put("url", url); put("title", title); put("raw_html", rawHtml)
            put("cleaned_text", cleaned); put("summary", summary); put("ts", System.currentTimeMillis())
        }, SQLiteDatabase.CONFLICT_REPLACE)
        return id
    }

    fun allDocuments(): List<LibraryDoc> =
        readableDatabase.rawQuery("SELECT id, url, title, summary, ts FROM documents ORDER BY ts DESC", null)
            .use { c -> buildList { while (c.moveToNext()) add(LibraryDoc(c.getString(0), c.getString(1) ?: "", c.getString(2) ?: "", c.getString(3) ?: "", c.getLong(4))) } }

    /** Desktop search_text: substring match on cleaned text (plus summary/title on Android). */
    fun searchDocuments(query: String, limit: Int = 10): List<LibraryDoc> {
        val q = "%${query.trim()}%"
        return readableDatabase.rawQuery(
            "SELECT id, url, title, summary, ts FROM documents WHERE cleaned_text LIKE ? OR summary LIKE ? OR title LIKE ? ORDER BY ts DESC LIMIT ?",
            arrayOf(q, q, q, limit.toString())
        ).use { c -> buildList { while (c.moveToNext()) add(LibraryDoc(c.getString(0), c.getString(1) ?: "", c.getString(2) ?: "", c.getString(3) ?: "", c.getLong(4))) } }
    }

    fun deleteDocument(id: String) { writableDatabase.delete("documents", "id=?", arrayOf(id)) }

    fun deleteDocumentsBefore(ts: Long): Int = writableDatabase.delete("documents", "ts<?", arrayOf(ts.toString()))
}
