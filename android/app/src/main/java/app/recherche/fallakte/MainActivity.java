package app.recherche.fallakte;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import com.chaquo.python.PyException;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.FileOutputStream;
import java.util.Collections;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/**
 * Einzige Activity: startet Python, dann den lokalen Server des Pakets "recherche" und zeigt
 * dessen Seite in einer WebView. In die WebView wird nur der lokale Server geladen; alles
 * andere geht, wenn es http(s) ist, an den Browser des Nutzers.
 */
public class MainActivity extends Activity {

    private static final String TAG = "recherche";
    private static final Pattern SLUG = Pattern.compile("[a-z0-9][a-z0-9-]*");
    private static final int SLUG_MAX = 120;
    private static final int REQ_IMPORT = 1001;
    private static final int REQ_DATEI = 1002;
    private static final long MAX_ALTER_MS = 24L * 60 * 60 * 1000;

    // Der Server lebt so lange wie der Prozess; eine neu erzeugte Activity nimmt ihn wieder auf.
    private static final Object LOCK = new Object();
    private static String serverUrl;
    private static volatile int serverPort;

    private final ExecutorService arbeit = Executors.newSingleThreadExecutor();
    private WebView web;
    private TextView status;
    private ValueCallback<Uri[]> dateiAntwort;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout wurzel = new FrameLayout(this);
        status = new TextView(this);
        status.setText("Recherche wird geladen …");
        status.setTextSize(18);
        status.setGravity(Gravity.CENTER);
        web = new WebView(this);
        web.setVisibility(View.INVISIBLE);
        wurzel.addView(status, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        wurzel.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(wurzel);

        richteWebViewEin();
        arbeit.execute(this::startePython);
    }

    @Override
    protected void onDestroy() {
        if (dateiAntwort != null) {
            dateiAntwort.onReceiveValue(null);
            dateiAntwort = null;
        }
        if (web != null) {
            web.destroy();
        }
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.getVisibility() == View.VISIBLE && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    // ---------------------------------------------------------------- Start

    private void startePython() {
        raeumeCacheAuf();
        String url;
        synchronized (LOCK) {
            if (serverUrl == null) {
                try {
                    if (!Python.isStarted()) {
                        Python.start(new AndroidPlatform(getApplicationContext()));
                    }
                    Python py = Python.getInstance();
                    py.getModule("recherche");
                    String version = py.getModule("sys").get("version").toString().split(" ")[0];
                    Log.i(TAG, "python ok " + version);
                } catch (Throwable e) {
                    Log.e(TAG, "python fehlgeschlagen: " + e);
                    zeigeFehler("Python konnte nicht gestartet werden.");
                    return;
                }
                try {
                    File faelle = new File(getFilesDir(), "faelle");
                    //noinspection ResultOfMethodCallIgnored
                    faelle.mkdirs();
                    PyObject modul = Python.getInstance().getModule("recherche.web");
                    PyObject ergebnis = modul.callAttr("starte_im_hintergrund", faelle.getAbsolutePath());
                    serverUrl = ergebnis.asMap().get("url").toString();
                    serverPort = ergebnis.asMap().get("port").toInt();
                } catch (PyException e) {
                    String meldung = String.valueOf(e.getMessage());
                    if (meldung.contains("No module named 'recherche.web'")) {
                        Log.w(TAG, "recherche.web fehlt in diesem Build");
                        zeigeFehler("Oberfläche fehlt in diesem Build");
                    } else {
                        Log.e(TAG, "server fehlgeschlagen: " + meldung);
                        zeigeFehler("Oberfläche konnte nicht gestartet werden.");
                    }
                    return;
                } catch (Throwable e) {
                    Log.e(TAG, "server fehlgeschlagen: " + e);
                    zeigeFehler("Oberfläche konnte nicht gestartet werden.");
                    return;
                }
            }
            url = serverUrl;
        }
        Log.i(TAG, "server ok");
        runOnUiThread(() -> {
            if (!isDestroyed()) {
                web.loadUrl(url);
            }
        });
    }

    private void zeigeFehler(String text) {
        runOnUiThread(() -> {
            if (status != null) {
                status.setText(text);
            }
        });
    }

    /** Loescht Dateien in den Export- und Import-Verzeichnissen, die aelter als ein Tag sind. */
    private void raeumeCacheAuf() {
        long grenze = System.currentTimeMillis() - MAX_ALTER_MS;
        loescheAlte(new File(getCacheDir(), "export"), grenze);
        loescheAlte(new File(getCacheDir(), "import"), grenze);
    }

    private static void loescheAlte(File ordner, long grenze) {
        File[] inhalt = ordner.listFiles();
        if (inhalt == null) {
            return;
        }
        for (File f : inhalt) {
            if (f.isDirectory()) {
                loescheAlte(f, grenze);
            }
            if (f.lastModified() < grenze) {
                //noinspection ResultOfMethodCallIgnored
                f.delete();
            }
        }
    }

    // ---------------------------------------------------------------- WebView

    private void richteWebViewEin() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setAllowFileAccessFromFileURLs(false);
        s.setAllowUniversalAccessFromFileURLs(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setSupportMultipleWindows(false);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setGeolocationEnabled(false);
        s.setSaveFormData(false);

        web.addJavascriptInterface(new Bruecke(), "Android");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (istLokal(uri)) {
                    return false;
                }
                if (istWeb(uri)) {
                    oeffneImBrowser(uri);
                }
                return true;
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                if (istLokal(request.getUrl())) {
                    return null;
                }
                // Die Seite selbst holt nichts von aussen.
                return new WebResourceResponse("text/plain", "utf-8", 403, "Forbidden",
                        Collections.<String, String>emptyMap(), new ByteArrayInputStream(new byte[0]));
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (view.getVisibility() != View.VISIBLE) {
                    view.setVisibility(View.VISIBLE);
                    status.setVisibility(View.GONE);
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> antwort,
                                             FileChooserParams params) {
                if (dateiAntwort != null) {
                    dateiAntwort.onReceiveValue(null);
                }
                dateiAntwort = antwort;
                try {
                    startActivityForResult(params.createIntent(), REQ_DATEI);
                } catch (ActivityNotFoundException e) {
                    dateiAntwort = null;
                    antwort.onReceiveValue(null);
                }
                return true;
            }
        });
    }

    private static boolean istLokal(Uri uri) {
        if (uri == null || !"http".equals(uri.getScheme())) {
            return false;
        }
        String host = uri.getHost();
        if (!"127.0.0.1".equals(host) && !"localhost".equals(host)) {
            return false;
        }
        int port = serverPort;
        return port != 0 && uri.getPort() == port;
    }

    private static boolean istWeb(Uri uri) {
        if (uri == null) {
            return false;
        }
        String schema = uri.getScheme();
        return ("http".equals(schema) || "https".equals(schema)) && uri.getHost() != null;
    }

    private void oeffneImBrowser(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            zeigeToast("Kein Browser gefunden.");
        }
    }

    // ---------------------------------------------------------------- Ergebnisse von Auswahldialogen

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == REQ_DATEI) {
            if (dateiAntwort != null) {
                dateiAntwort.onReceiveValue(
                        WebChromeClient.FileChooserParams.parseResult(resultCode, data));
                dateiAntwort = null;
            }
            return;
        }
        if (requestCode == REQ_IMPORT) {
            if (resultCode == RESULT_OK && data != null && data.getData() != null) {
                Uri quelle = data.getData();
                arbeit.execute(() -> importiere(quelle));
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    // ---------------------------------------------------------------- Aktionen

    private void importiere(Uri quelle) {
        File ordner = new File(getCacheDir(), "import");
        //noinspection ResultOfMethodCallIgnored
        ordner.mkdirs();
        File ziel = new File(ordner, "import-" + System.currentTimeMillis() + ".zip");
        try {
            try (InputStream in = getContentResolver().openInputStream(quelle);
                 OutputStream out = new FileOutputStream(ziel)) {
                if (in == null) {
                    throw new IOException("Datei nicht lesbar");
                }
                byte[] puffer = new byte[64 * 1024];
                int n;
                while ((n = in.read(puffer)) > 0) {
                    out.write(puffer, 0, n);
                }
            }
            PyObject ergebnis = recherchWeb().callAttr("importiere", ziel.getAbsolutePath());
            zeigeToast(String.valueOf(ergebnis));
            runOnUiThread(() -> {
                if (!isDestroyed()) {
                    web.evaluateJavascript(
                            "window.recherche && window.recherche.neuLaden && window.recherche.neuLaden();",
                            null);
                }
            });
        } catch (PyException e) {
            Log.w(TAG, "import fehlgeschlagen");
            zeigeToast("Import fehlgeschlagen: " + e.getMessage());
        } catch (Exception e) {
            Log.w(TAG, "import fehlgeschlagen: " + e.getClass().getSimpleName());
            zeigeToast("Import fehlgeschlagen: " + e.getMessage());
        } finally {
            //noinspection ResultOfMethodCallIgnored
            ziel.delete();
        }
    }

    private void teile(String funktion, String slug, File ordner, String fehlerText) {
        try {
            //noinspection ResultOfMethodCallIgnored
            ordner.mkdirs();
            PyObject ergebnis = recherchWeb().callAttr(funktion, slug, ordner.getAbsolutePath());
            File datei = new File(String.valueOf(ergebnis)).getCanonicalFile();
            if (!datei.getPath().startsWith(ordner.getCanonicalPath() + File.separator)
                    || !datei.isFile()) {
                throw new IOException("Datei liegt nicht im Exportverzeichnis");
            }
            Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", datei);
            String endung = MimeTypeMap.getFileExtensionFromUrl(datei.getName());
            String typ = endung == null ? null
                    : MimeTypeMap.getSingleton().getMimeTypeFromExtension(endung.toLowerCase(Locale.ROOT));
            Intent senden = new Intent(Intent.ACTION_SEND);
            senden.setType(typ != null ? typ : "application/octet-stream");
            senden.putExtra(Intent.EXTRA_STREAM, uri);
            senden.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            Intent auswahl = Intent.createChooser(senden, null);
            runOnUiThread(() -> {
                try {
                    startActivity(auswahl);
                } catch (ActivityNotFoundException e) {
                    zeigeToast("Keine App zum Teilen gefunden.");
                }
            });
        } catch (PyException e) {
            Log.w(TAG, fehlerText);
            zeigeToast(fehlerText + ": " + e.getMessage());
        } catch (Exception e) {
            Log.w(TAG, fehlerText + ": " + e.getClass().getSimpleName());
            zeigeToast(fehlerText + ": " + e.getMessage());
        }
    }

    private PyObject recherchWeb() {
        return Python.getInstance().getModule("recherche.web");
    }

    private void zeigeToast(String text) {
        runOnUiThread(() -> Toast.makeText(this, text, Toast.LENGTH_LONG).show());
    }

    private static boolean slugOk(String slug) {
        return slug != null && slug.length() <= SLUG_MAX && SLUG.matcher(slug).matches();
    }

    /**
     * Von der Seite aus erreichbar als window.Android. Ausser dem lokalen Server laedt nichts
     * in die WebView; diese Methoden sind deshalb nur fuer die eigene Seite sichtbar.
     */
    private final class Bruecke {

        @JavascriptInterface
        public void importieren() {
            runOnUiThread(() -> {
                Intent wahl = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                wahl.addCategory(Intent.CATEGORY_OPENABLE);
                wahl.setType("*/*");
                wahl.putExtra(Intent.EXTRA_MIME_TYPES,
                        new String[]{"application/zip", "application/x-zip-compressed",
                                "application/octet-stream"});
                try {
                    startActivityForResult(wahl, REQ_IMPORT);
                } catch (ActivityNotFoundException e) {
                    zeigeToast("Keine Dateiauswahl gefunden.");
                }
            });
        }

        @JavascriptInterface
        public void exportieren(String slug) {
            if (!slugOk(slug)) {
                zeigeToast("Ungültiger Fallname.");
                return;
            }
            arbeit.execute(() -> teile("exportiere", slug, new File(getCacheDir(), "export"),
                    "Export fehlgeschlagen"));
        }

        @JavascriptInterface
        public void dossierTeilen(String slug) {
            if (!slugOk(slug)) {
                zeigeToast("Ungültiger Fallname.");
                return;
            }
            arbeit.execute(() -> teile("dossier_datei", slug, new File(getCacheDir(), "export"),
                    "Dossier fehlgeschlagen"));
        }

        @JavascriptInterface
        public void oeffneExtern(String url) {
            Uri uri = url == null ? null : Uri.parse(url);
            // Nicht die eigene Seite (mit Token) in den Browser geben.
            if (istWeb(uri) && !istLokalerHost(uri)) {
                runOnUiThread(() -> oeffneImBrowser(uri));
            }
        }
    }

    private static boolean istLokalerHost(Uri uri) {
        String host = uri.getHost();
        return "127.0.0.1".equals(host) || "localhost".equals(host);
    }
}
