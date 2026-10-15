#include "portlang.h"

#include <stdio.h>
#include <string.h>

#include "langtab.h"

// One row a string: English, French, German, Italian, Spanish, Swedish, in
// LangEnum's order. Latin-1, as retail's tables are, so each accent is its
// byte. "$NAME", "$N" and "$MAX" are filled in by whoever shows the line,
// and '@' breaks it, as in retail's.
static const char* const kStrings[PORTLANG_END - PORTLANG_FIRST][6] = {
    // PORTLANG_LOCAL_WIRELESS
    { "Local Wireless", "Sans fil local", "Lokal kabellos",
      "Wireless locale", "Inal\xe1mbrico local", "Lokalt tr\xe5" "dl\xf6st" },
    // PORTLANG_LOCAL_WIRELESS_BLURB
    { "Up to eight players, each on their own 3DS.",
      "Jusqu'\xe0 huit joueurs, chacun sur sa 3DS.",
      "Bis zu acht Spieler, jeder an seinem 3DS.",
      "Fino a otto giocatori, ognuno con il suo 3DS.",
      "Hasta ocho jugadores, cada uno con su 3DS.",
      "Upp till \xe5tta spelare, var och en med sin 3DS." },
    // PORTLANG_HOST
    { "Host", "Cr\xe9" "er", "Erstellen", "Crea", "Crear", "Skapa" },
    // PORTLANG_JOIN
    { "Join", "Rejoindre", "Beitreten", "Unisciti", "Unirse", "G\xe5 med" },
    // PORTLANG_HOST_OR_JOIN
    { "Host a race, or join one?",
      "Cr\xe9" "er une course ou en rejoindre une ?",
      "Ein Rennen erstellen oder einem beitreten?",
      "Creare una gara o unirsi a una?",
      "\xbf" "Crear una carrera o unirse a una?",
      "Skapa ett lopp eller g\xe5 med i ett?" },
    // PORTLANG_SEARCHING
    { "Looking for races...", "Recherche de courses...",
      "Suche nach Rennen...", "Ricerca di gare...", "Buscando carreras...",
      "Letar efter lopp..." },
    // PORTLANG_FOUND
    { "Race: $NAME@Players: $N/$MAX", "Course : $NAME@Joueurs : $N/$MAX",
      "Rennen: $NAME@Spieler: $N/$MAX", "Gara: $NAME@Giocatori: $N/$MAX",
      "Carrera: $NAME@Jugadores: $N/$MAX", "Lopp: $NAME@Spelare: $N/$MAX" },
    // PORTLANG_NEXT
    { "Next", "Suivant", "Weiter", "Avanti", "Siguiente", "N\xe4sta" },
    // PORTLANG_WAITING_FOR_PLAYERS
    { "Waiting for players:", "En attente de joueurs :",
      "Warte auf Spieler:", "In attesa di giocatori:",
      "Esperando jugadores:", "V\xe4ntar p\xe5 spelare:" },
    // PORTLANG_WAITING_FOR_HOST
    { "Waiting for $NAME to start the race.",
      "En attente du lancement de la course par $NAME.",
      "Warte, bis $NAME das Rennen startet.",
      "In attesa che $NAME avvii la gara.",
      "Esperando a que $NAME inicie la carrera.",
      "V\xe4ntar p\xe5 att $NAME startar loppet." },
    // PORTLANG_START
    { "Start", "Lancer", "Starten", "Avvia", "Empezar", "Starta" },
    // PORTLANG_LINK_LOST
    { "The link to $NAME was lost.",
      "La liaison avec $NAME a \xe9t\xe9 perdue.",
      "Die Verbindung zu $NAME ist abgebrochen.",
      "Il collegamento con $NAME si \xe8 interrotto.",
      "Se perdi\xf3 la conexi\xf3n con $NAME.",
      "Anslutningen till $NAME br\xf6ts." },
    // PORTLANG_WIRELESS_OFF: with the console's wireless on, which
    // PORTLANG_WIRELESS_DISABLED says when it is not
    { "Local wireless could not start. Please try again.",
      "Impossible de lancer le sans-fil local. Veuillez r\xe9" "essayer.",
      "Lokal kabellos konnte nicht starten. Bitte versuche es erneut.",
      "Impossibile avviare il wireless locale. Riprova.",
      "No se pudo iniciar el modo inal\xe1mbrico local. Int\xe9ntalo de "
      "nuevo.",
      "Lokalt tr\xe5" "dl\xf6st kunde inte starta. F\xf6rs\xf6k igen." },
    // PORTLANG_JOIN_FAILED
    { "Could not join the race.", "Impossible de rejoindre la course.",
      "Beitritt zum Rennen fehlgeschlagen.",
      "Impossibile unirsi alla gara.", "No se pudo unir a la carrera.",
      "Kunde inte g\xe5 med i loppet." },
    // PORTLANG_WAITING_FOR_CARS
    { "Waiting for a car from:", "En attente de la voiture de :",
      "Warte auf das Auto von:", "In attesa dell'auto di:",
      "Esperando el coche de:", "V\xe4ntar p\xe5 bil fr\xe5n:" },
    // PORTLANG_CPU_RACERS
    { "CPU Racers", "Pilotes IA", "KI-Fahrer", "Piloti CPU", "Pilotos CPU",
      "Datorf\xf6rare" },
    // PORTLANG_CPU_RACERS_N
    { "CPU racers: $N", "Pilotes IA : $N", "KI-Fahrer: $N",
      "Piloti CPU: $N", "Pilotos CPU: $N", "Datorf\xf6rare: $N" },
    // PORTLANG_WIRELESS_DISABLED
    { "Wireless communication is turned off. Turn it on from the HOME "
      "Menu to play over Local Wireless.",
      "La communication sans fil est d\xe9sactiv\xe9" "e. Activez-la "
      "depuis le menu HOME pour jouer en sans fil local.",
      "Die Drahtlos-Kommunikation ist deaktiviert. Aktiviere sie im "
      "HOME-Men\xfc, um lokal kabellos zu spielen.",
      "La comunicazione wireless \xe8 disattivata. Attivala dal menu HOME "
      "per giocare in wireless locale.",
      "La conexi\xf3n inal\xe1mbrica est\xe1 desactivada. Act\xedvala "
      "desde el men\xfa HOME para jugar en modo inal\xe1mbrico local.",
      "Tr\xe5" "dl\xf6s kommunikation \xe4r avst\xe4ngd. Sl\xe5 p\xe5 den "
      "fr\xe5n HOME-menyn f\xf6r att spela lokalt tr\xe5" "dl\xf6st." },
    // PORTLANG_HOST_MODE: its buttons are the main menu's two modes,
    // retail's 10023 and 10022
    { "Which mode will you host?",
      "Quel mode voulez-vous cr\xe9" "er ?",
      "Welchen Modus willst du erstellen?",
      "Quale modalit\xe0 vuoi creare?",
      "\xbf" "Qu\xe9 modo quieres crear?",
      "Vilket l\xe4ge vill du skapa?" },
    // PORTLANG_RECONNECTING: $N is the time left, m:ss
    { "Reconnecting... $N", "Reconnexion... $N",
      "Verbindung wird wiederhergestellt... $N", "Riconnessione... $N",
      "Reconectando... $N", "\xc5teransluter... $N" },
    // PORTLANG_CPU_DRIVES
    { "The CPU drives $NAME's car.", "L'IA conduit la voiture de $NAME.",
      "Die KI f\xe4hrt das Auto von $NAME.", "La CPU guida l'auto di $NAME.",
      "La CPU conduce el coche de $NAME.", "Datorn k\xf6r $NAMEs bil." },
};

const char* portlang_get(int32_t languageEnum, int32_t id, size_t* outLen)
{
    static char        number[PORTLANG_END - PORTLANG_FIRST][12];
    const char* const* row;
    const char*        s;

    if (id < PORTLANG_FIRST || id >= PORTLANG_END)
        return NULL;
    row = kStrings[id - PORTLANG_FIRST];
    if (languageEnum == LANG_ID_NUM) {
        s = number[id - PORTLANG_FIRST];
        if (!s[0])
            snprintf(number[id - PORTLANG_FIRST], sizeof number[0], "%ld",
                     (long)id);
    } else if (languageEnum == LANG_LONGEST) {
        int i;

        s = row[0];
        for (i = 1; i < 6; i++)
            if (strlen(row[i]) > strlen(s))
                s = row[i];
    } else {
        s = row[languageEnum >= LANG_EN && languageEnum <= LANG_SE
                    ? languageEnum : LANG_EN];
    }
    if (outLen)
        *outLen = strlen(s);
    return s;
}
