// SPDX-License-Identifier: GPL-3.0-or-later
// KAIROS for Android — Developed by RC. Chat history + retained memory (desktop: knowledge.py remember/recall).
package org.kairos.agent.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

data class StoredMessage(val id: Long, val role: String, val content: String, val ts: Long)
data class Memory(val id: Long, val content: String, val ts: Long)

class MemoryStore(context: Context, name: String? = "kairos.db") :
    SQLiteOpenHelper(context, name, null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, ts INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE memories(id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL UNIQUE, ts INTEGER NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

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
}
