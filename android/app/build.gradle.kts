plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "org.kairos.agent"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.kairos.agent"
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = "0.16.5-android.1"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    // Release signing comes from environment variables (CI secrets) only.
    // No keystore or password is ever committed to the repository.
    signingConfigs {
        create("release") {
            val ks = System.getenv("KAIROS_KEYSTORE")
            if (ks != null) {
                storeFile = file(ks)
                storePassword = System.getenv("KAIROS_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KAIROS_KEY_ALIAS")
                keyPassword = System.getenv("KAIROS_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (System.getenv("KAIROS_KEYSTORE") != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    // Reproducible builds for F-Droid: no dependency metadata blob in the APK.
    dependenciesInfo {
        includeInApk = false
        includeInBundle = false
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    testOptions { unitTests.isReturnDefaultValues = true }
    packaging {
        // youtubedl-android executes libpython/ffmpeg from nativeLibraryDir, so they must be extracted.
        jniLibs.useLegacyPackaging = true
        resources.excludes += setOf("META-INF/LICENSE.md", "META-INF/NOTICE.md", "about.html", "plugin.properties")
        resources.pickFirsts += setOf("META-INF/mailcap", "META-INF/mailcap.default", "META-INF/mimetypes.default", "META-INF/javamail.providers", "META-INF/javamail.default.providers", "META-INF/javamail.default.address.map")
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jsoup:jsoup:1.18.3") // MIT
    // Jakarta Mail for Android: EPL-2.0 OR GPL-2.0-with-Classpath-exception
    implementation("com.sun.mail:android-mail:1.6.7")
    implementation("com.sun.mail:android-activation:1.6.7")
    // Mozilla Rhino JavaScript engine for the skill sandbox: MPL-2.0, pure Java
    implementation("org.mozilla:rhino:1.7.15")
    // JGit for git workflows: EDL-1.0 (BSD-3-Clause). 5.13 is the last line targeting Java 8 APIs.
    implementation("org.eclipse.jgit:org.eclipse.jgit:5.13.3.202401111512-r")
    // yt-dlp + Python + ffmpeg for media downloads: GPL-3.0 (approved by the owner)
    implementation("io.github.junkfood02.youtubedl-android:library:0.18.1")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.18.1")
    // Vosk offline speech recognition: Apache-2.0 (approved by the owner); pulls JNA (LGPL-2.1/Apache-2.0)
    implementation("com.alphacephei:vosk-android:0.3.75")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    // In-process IMAP/SMTP server for email tests (Apache-2.0); uses the app's javax.mail classes.
    testImplementation("com.icegreen:greenmail:1.6.15") {
        exclude(group = "com.sun.mail", module = "javax.mail")
        exclude(group = "javax.activation")
    }
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
