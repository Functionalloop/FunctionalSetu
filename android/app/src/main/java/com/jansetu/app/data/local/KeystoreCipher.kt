package com.jansetu.app.data.local

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import dagger.hilt.android.qualifiers.ApplicationContext
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Encrypts small secrets with an AES-256-GCM key that never leaves the Android Keystore.
 * Output = base64(iv || ciphertext). Used for the database key and the login tokens.
 */
class KeystoreCipher(private val alias: String) {
    private val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private fun key(): SecretKey =
        (keyStore.getEntry(alias, null) as? KeyStore.SecretKeyEntry)?.secretKey
            ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE).run {
                init(
                    KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setKeySize(256)
                        .build(),
                )
                generateKey()
            }

    fun encrypt(plain: ByteArray): String {
        val c = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()) }
        return Base64.encodeToString(c.iv + c.doFinal(plain), Base64.NO_WRAP)
    }

    fun decrypt(stored: String): ByteArray {
        val all = Base64.decode(stored, Base64.NO_WRAP)
        val c = Cipher.getInstance(TRANSFORMATION)
        c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, all, 0, IV_BYTES))
        return c.doFinal(all, IV_BYTES, all.size - IV_BYTES)
    }

    fun deleteKey() {
        if (keyStore.containsAlias(alias)) keyStore.deleteEntry(alias)
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
    }
}

/**
 * The SQLCipher key: 32 random bytes made on first use, stored only encrypted by the Keystore.
 * Passed as a raw key (x'..') so SQLCipher skips its slow password stretching on every open.
 */
@Singleton
class DbKey @Inject constructor(@ApplicationContext context: Context) {
    private val prefs = context.getSharedPreferences("jansetu_db_key", Context.MODE_PRIVATE)
    private val cipher = KeystoreCipher("jansetu_db")

    /** The key, and whether it was just made (then any old database file cannot be opened). */
    @Synchronized
    fun passphrase(): Pair<ByteArray, Boolean> {
        val old = prefs.getString(PREF, null)?.let { stored -> runCatching { cipher.decrypt(stored) }.getOrNull() }
        val raw = old ?: ByteArray(32).also { SecureRandom().nextBytes(it) }.also {
            prefs.edit().putString(PREF, cipher.encrypt(it)).commit()
        }
        val hex = raw.joinToString("") { "%02x".format(it) }
        return "x'$hex'".toByteArray(Charsets.US_ASCII) to (old == null)
    }

    @Synchronized
    fun forget() {
        prefs.edit().clear().commit()
        cipher.deleteKey()
    }

    private companion object { const val PREF = "wrapped" }
}
