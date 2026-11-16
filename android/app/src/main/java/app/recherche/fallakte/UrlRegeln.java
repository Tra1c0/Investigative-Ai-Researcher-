package app.recherche.fallakte;

import android.net.Uri;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Welche Adressen die App lädt oder an den Browser gibt. Die Regeln sind bewusst eng: Die
 * WebView trägt die Brücke zu Import und Export, der Browser darf nur gewöhnliche
 * Internetadressen bekommen.
 */
final class UrlRegeln {

    private static final int MAX_LAENGE = 2048;
    private static final Pattern HOST_ZEICHEN = Pattern.compile("[a-z0-9.-]+");
    private static final Pattern LABEL = Pattern.compile("[a-z0-9-]+");
    // Browser lesen einen Host als IPv4-Adresse, wenn sein letztes Label eine Zahl ist,
    // dezimal, oktal oder hexadezimal (127.1, 0x7f.1, 2130706433).
    private static final Pattern ZAHL_LABEL = Pattern.compile("[0-9]+|0x[0-9a-f]*");

    private UrlRegeln() {
    }

    /**
     * Die eigene Seite: genau der Ursprung http://127.0.0.1:port des Servers. Verglichen wird
     * der Anfang der Zeichenkette, nicht der Host, den android.net.Uri herausliest: Bei
     * "http://fremd.example\@127.0.0.1:port/" liest Uri 127.0.0.1 als Host, Chromium behandelt
     * den Rückwärtsstrich aber wie einen Schrägstrich und lädt fremd.example.
     */
    static boolean istEigeneSeite(String url, int port) {
        if (url == null || port <= 0) {
            return false;
        }
        String ursprung = "http://127.0.0.1:" + port;
        if (!url.startsWith(ursprung)) {
            return false;
        }
        if (url.length() == ursprung.length()) {
            return true;
        }
        char danach = url.charAt(ursprung.length());
        return danach == '/' || danach == '?' || danach == '#';
    }

    /**
     * Gibt die Adresse zurück, wenn sie im Browser geöffnet werden darf, sonst null.
     * Erlaubt sind http und https auf einen Hostnamen mit Punkt, ohne Benutzerangabe, der
     * weder localhost noch eine IP-Adresse in irgendeiner Schreibweise ist.
     */
    static String externeAdresse(String url) {
        if (url == null || url.isEmpty() || url.length() > MAX_LAENGE) {
            return null;
        }
        for (int i = 0; i < url.length(); i++) {
            char c = url.charAt(i);
            if (c == '\\' || Character.isWhitespace(c) || Character.isSpaceChar(c)
                    || Character.isISOControl(c)) {
                return null;
            }
        }
        URI java;
        try {
            java = new URI(url);
        } catch (URISyntaxException e) {
            return null;
        }
        Uri android = Uri.parse(url);

        String schema = java.getScheme();
        if (schema == null || android.getScheme() == null
                || !schema.equalsIgnoreCase(android.getScheme())) {
            return null;
        }
        schema = schema.toLowerCase(Locale.ROOT);
        if (!schema.equals("http") && !schema.equals("https")) {
            return null;
        }
        if (java.getRawUserInfo() != null || android.getUserInfo() != null) {
            return null;
        }
        if (java.getPort() > 65535) {
            return null;
        }
        String javaHost = java.getHost();
        String androidHost = android.getHost();
        if (javaHost == null || androidHost == null || !javaHost.equalsIgnoreCase(androidHost)) {
            return null;
        }
        return hostOk(javaHost) ? url : null;
    }

    static boolean hostOk(String host) {
        String h = host.toLowerCase(Locale.ROOT);
        if (h.endsWith(".")) {
            h = h.substring(0, h.length() - 1);
        }
        // Nur ASCII-Buchstaben, Ziffern, Bindestrich und Punkt: schließt Klammern (IPv6),
        // Doppelpunkte und Nicht-ASCII-Ziffern aus, die Browser zu IP-Adressen umrechnen.
        if (!HOST_ZEICHEN.matcher(h).matches() || h.indexOf('.') < 0) {
            return false;
        }
        if (h.equals("localhost") || h.endsWith(".localhost")) {
            return false;
        }
        String[] labels = h.split("\\.", -1);
        for (String label : labels) {
            if (!LABEL.matcher(label).matches()) {
                return false;
            }
        }
        return !ZAHL_LABEL.matcher(labels[labels.length - 1]).matches();
    }
}
