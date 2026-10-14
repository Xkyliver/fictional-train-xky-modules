import java.io.FileInputStream;
import java.security.KeyStore;
import java.security.Security;
import java.util.Enumeration;
import org.bouncycastle.jce.provider.BouncyCastleProvider;

public class CheckKS {
    public static void main(String[] args) {
        Security.addProvider(new BouncyCastleProvider());
        String[] testPasses = new String[] { "", "changeit", "morphe", "Morphe_Xky", "android" };
        
        for (String p : testPasses) {
            try (FileInputStream fis = new FileInputStream("morphe.keystore")) {
                KeyStore ks = KeyStore.getInstance("BKS");
                ks.load(fis, p.toCharArray());
                System.out.println(">>> Store password matches: '" + p + "'");
                
                Enumeration<String> aliases = ks.aliases();
                while (aliases.hasMoreElements()) {
                    String alias = aliases.nextElement();
                    System.out.println("  Alias: " + alias);
                    for (String kp : testPasses) {
                        try {
                            if (ks.getKey(alias, kp.toCharArray()) != null) {
                                System.out.println("  >>> Key password for alias '" + alias + "' matches: '" + kp + "'");
                            }
                        } catch (Exception ignored) {}
                    }
                }
                return;
            } catch (Exception ignored) {}
        }
        System.out.println("None of the common passwords matched the keystore.");
    }
}
