// Host harness for the Local Wireless lobby (lobby.c, TASKS 37b).
//
// Builds "3DS Files/source/lobby.c" with the flow and its popups
// (gameflow.c, bpopup.c) over a fake link: a script of the consoles that
// come and go on a hosted network, the races in range of a joiner, and
// what a joined host does, all on the frame count. Each scenario starts
// on a screen "Prev", goes to the lobby as the main menu's Local Wireless
// does (pushed), and presses A, B and the D-pad on given frames, 60 a
// second. The host's setup (TASKS 63) is two screens of nothing, the
// Challenge and Single Race Setup, whose select and BACK are presses too.
//
// Nothing of retail's is ported here, so there is no model to diff. The
// harness checks these each frame and prints a FAULT for each it finds:
//
//   - one popup at most, and only on the lobby's screen, its parent the
//     lobby;
//   - the question (Host or Join) only with the link down, and Host's
//     question of the mode too, its buttons the main menu's Hot Pursuit
//     and World Racing;
//   - the setup told on (lobby_on_setup) exactly while a setup screen is
//     up, and the link down there;
//   - the host's popup lists this console, then each client still on, in
//     the order they came, with Start once there is one; with a CPU
//     racer wish (TASKS 37c-2) a last line says as many as wished of
//     those that fit on the 8-car grid, and CPU Racers (after Start, or
//     alone) counts one more, none past those that fit, the highlight
//     kept on it until a move to Start; never more than nine lines;
//   - a joiner's waiting popup names the host it joined;
//   - a scan only with UDS up and on no network; while searching, none
//     within LOBBY_SCAN_MS of the last unless a search just began or Next
//     asked for it; and a search begun (not on a scan that found nothing)
//     scans on that frame;
//   - no popup put up again just as it was on a frame with no press;
//   - no sound on a frame with no press; A on a popup with no buttons
//     makes none and says nothing, A on a button the select sound, B the
//     cancel sound, and left or right the move sound when there are two;
//   - all of this again straight after the frame's presses, before the
//     flow's tick;
//   - the lobby left back to Prev with the link down, and on to Select Car
//     with it up: the host's network closed and each client still on sent
//     one LOBBY_MSG_START with the count, its place, the host's game type
//     and its cops, a joiner having read one; the start told once, with
//     the CPU racers the host's list showed (none on a joiner or with no
//     choice) and the host's mode (on a joiner, the one it read); and
//     under car select only Prev and the lobby on the stack, whatever
//     setup screens the host went through;
//   - with the console's wireless communication off (TASKS 62): no start,
//     host, scan or join asked of the link, and the lobby's link down by
//     the end of the frame it went off on;
//   - back from the race (TASKS 37f, the key "RB"): the frontend back on
//     the lobby by gameflow's raceReturn; a host's network open again and
//     each client still on sent one LOBBY_MSG_BACK, a joiner's one sent to
//     the host; a client listed once its own is read, and Start only once
//     every client still on is; the link's timeout the race's until every
//     other console still on is back, then the link's own, given back
//     once; the next race's start as the first's; a client gone while
//     awaited, its place taken by the next, and one who comes after listed
//     at once; the link taken down and up again with nobody awaited, and
//     no return left over for the next time the lobby comes up;
//
// and at the end the scenario's own: the screen it ends on, the link up
// or down, and the lobby's log lines it must have said, in order.
//
//     scenario <name>
//     <the flow's trace, the lobby's log, the fake's calls, the presses>
//     final <screen> link <0|1>
//     faults <n>                   (after every scenario)
//     total faults <n>
//
// Usage: lobby_test [scenario]...      (no argument runs them all)

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bpopup.h"
#include "gameflow.h"
#include "langtab.h"
#include "lobby.h"
#include "portlang.h"

#define SIXTIETH (1.0f / 60.0f)
#define MAX_CLIENTS 8   // over a scenario; WIRELESS_MAX_PEERS at once
#define MAX_RACES   4
#define MAX_INPUTS  24
#define MAX_EXPECT  16

// ------------------------------------------------------------ scenarios

typedef struct {
    const char* name;      // UTF-8
    int         joinAt;    // the frame it comes, once the network is open
    int         leaveAt;   // the frame it goes, 0 never
    int         backAfter; // frames after the race's return it says it is
                           // back, 0 never
} Client;

typedef struct {
    const char* name;      // the host's, UTF-8
    int         consoles, max;
    int         from, until;   // the frames it is in range; until 0, always
} Race;

typedef struct {
    int         frame;
    const char* key;       // "A", "B", "L", "R"; "CB" is B on car select,
                           // "X" a change to Prev from outside the lobby,
                           // "N" the race's notice for the lobby's return
                           // (lobby_notice_next: the link to hp2host lost);
                           // on a setup screen "S" its select, "SB" its
                           // BACK and "SS" the Challenge's Setup; "H" is
                           // A, then A on Hot Pursuit if the mode is
                           // asked, then S if a setup screen is up; "RB"
                           // on car select is the race run and over, the
                           // frontend back after it (netrace_end)
} Input;

typedef struct {
    const char* name;
    int         frames;
    int         language;
    int         noWireless;     // UDS will not start
    int         hostFails;      // the network cannot be made
    int         joinFails;      // a join refused
    const char* self;           // this console's name
    Client      clients[MAX_CLIENTS];
    Race        races[MAX_RACES];
    int         startAfter;     // frames after a join that the host starts
    int         lostAfter;      // frames after a join that the host goes
    Input       input[MAX_INPUTS];
    const char* endScreen;
    int         endLink;
    const char* expect[MAX_EXPECT];
    int         hostDropAt;     // the frame the hosted network goes, 0 never
    int         junkFirst;      // a joined host sends another message first
    int         cpuFn;          // a CPU racer wish (lobby_cpu_wish), and
    int         cpuWish;        // what it says at each hosting
    int         radioOffFrom;   // the frame the console's wireless goes
    int         radioOffUntil;  // off, 0 never; and comes on, 0 never
    int         shortStart;     // a joined host's start of two bytes, a
                                // host from before TASKS 63
    int         hostBackAfter;  // a joined host says it is back this many
                                // frames after the race's return, 0 never
    int         restartAfter;   // and starts again after this many, 0
                                // never
} Scenario;

// The link's timeout netrace_end leaves for the lobby (netrace.h).
#define RACE_PATIENCE 30000u

// The game type the flow's hook answers on the host, and a joined host
// sends: a Single Race (fred.h).
#define HOST_GAME_TYPE 3

#define RADIO_OFF_LINE "lobby: notice Wireless communication is turned " \
                       "off. Turn it on from the HOME Menu to play over " \
                       "Local Wireless."
#define WIRELESS_OFF_LINE "lobby: notice Local wireless could not start. " \
                          "Please try again."

#define NONE {{0}}

static const Scenario kScenarios[] = {
    // B on the question: back where it came from, the link never up.
    { "back", 30, LANG_EN, 0, 0, 0, "hp2host", NONE, NONE, 0, 0,
      {{10, "B"}}, "Prev", 0,
      {"lobby: ask", "lobby: back"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // TASKS 63. Host asks the mode, Hot Pursuit highlighted; A goes to
    // the Challenge with the cops on, its select back to the lobby, which
    // hosts; a client, Start: the client told the host's mode.
    { "host_mode", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "A"}, {20, "A"}, {30, "S"}, {200, "A"}}, "Select Car", 1,
      {"lobby: ask", "lobby: mode", "flow: police 1", "flow: setup 1",
       "lobby: setup, cops on", "flow: setup 0", "lobby: setup done",
       "lobby: hosting", "lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: start, 2 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // World Racing: the cops off, and the highlight on it when the mode
    // is asked again.
    { "host_mode_world", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "A"}, {20, "R"}, {25, "A"}, {30, "S"}, {40, "B"}, {50, "A"},
       {60, "A"}, {70, "S"}, {200, "A"}}, "Select Car", 1,
      {"lobby: mode", "flow: police 0", "lobby: setup, cops off",
       "lobby: setup done", "lobby: hosting", "lobby: link down",
       "lobby: ask", "lobby: mode", "flow: police 0",
       "lobby: setup, cops off", "lobby: hosting",
       "lobby: start, 2 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // B on the mode: the question again; B again leaves.
    { "host_mode_back", 100, LANG_EN, 0, 0, 0, "hp2host", NONE, NONE, 0, 0,
      {{10, "A"}, {20, "B"}, {30, "B"}}, "Prev", 0,
      {"lobby: ask", "lobby: mode", "lobby: ask", "lobby: back"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // B on the Challenge: the mode again, the link never up, and the
    // setup told off.
    { "host_setup_back", 100, LANG_EN, 0, 0, 0, "hp2host", NONE, NONE, 0, 0,
      {{10, "A"}, {20, "A"}, {30, "SB"}, {40, "B"}, {50, "B"}}, "Prev", 0,
      {"flow: setup 1", "lobby: setup, cops on", "flow: setup 0",
       "lobby: setup left", "lobby: mode", "lobby: ask", "lobby: back"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // Through the Challenge's Setup to Single Race Setup and back to the
    // Challenge, then Setup again and its select: hosting, with the
    // setup screens off the stack, so B and B leave.
    { "host_setup_deep", 200, LANG_EN, 0, 0, 0, "hp2host", NONE, NONE, 0, 0,
      {{10, "A"}, {20, "A"}, {30, "SS"}, {40, "SB"}, {50, "SS"}, {60, "S"},
       {100, "B"}, {150, "B"}}, "Prev", 0,
      {"lobby: setup, cops on", "lobby: setup done", "lobby: hosting",
       "lobby: link down", "lobby: ask", "lobby: back"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // A client with the deep setup: car select over Prev and the lobby.
    { "host_setup_deep_start", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 100, 0, 0}}, NONE, 0, 0,
      {{10, "A"}, {20, "A"}, {30, "SS"}, {60, "S"}, {200, "A"}},
      "Select Car", 1,
      {"lobby: setup done", "lobby: hosting", "lobby: start, 2 consoles"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // The console's wireless turned off during the setup: back from it,
    // the line that says so, and no network made.
    { "host_setup_radio_off", 200, LANG_EN, 0, 0, 0, "hp2host", NONE, NONE,
      0, 0, {{10, "A"}, {20, "A"}, {60, "S"}, {100, "A"}}, "Local Wireless",
      0, {"lobby: setup, cops on", "lobby: setup done",
          "lobby: wireless communication off", RADIO_OFF_LINE,
          "lobby: ask"}, 0, 0, 0, 0, 40, 0, 0, 0, 0 },
    // A joiner of a host from before TASKS 63, whose start has no mode:
    // none told.
    { "join_start_short", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}}, "Select Car", 1,
      {"lobby: joined hp2host", "lobby: started by hp2host, place 1 of 2"},
      0, 0, 0, 0, 0, 0, 1, 0, 0 },

    // A host, one client, Start: on to car select with the link up.
    { "host_one", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 120, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}}, "Select Car", 1,
      {"lobby: ask", "lobby: hosting",
       "lobby: list Waiting for players:@hp2host",
       "lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: start, 2 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // A on the list before anyone came only puts it back; B then takes
    // the network down and asks again; B again leaves.
    { "host_alone", 200, LANG_EN, 0, 0, 0, "hp2host", NONE, NONE, 0, 0,
      {{10, "H"}, {60, "A"}, {90, "B"}, {130, "B"}}, "Prev", 0,
      {"lobby: hosting", "lobby: list Waiting for players:@hp2host",
       "lobby: link down", "lobby: ask", "lobby: back"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // Two clients, one of which goes on the frame Start is pressed: the
    // other is told it is one of two.
    { "host_one_goes", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}, {"hp2join2", 70, 200, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}}, "Select Car", 1,
      {"lobby: list Waiting for players:@hp2host@hp2join1@hp2join2",
       "lobby: start, 2 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // Seven clients fill the network; one goes, and its place is let go
    // so an eighth gets in.
    { "host_full", 700, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}, {"hp2join2", 70, 0, 0}, {"hp2join3", 80, 300, 0},
       {"hp2join4", 90, 0, 0}, {"hp2join5", 100, 0, 0}, {"hp2join6", 110, 0, 0},
       {"hp2join7", 120, 0, 0}, {"hp2join8", 200, 0, 0}},
      NONE, 0, 0,
      {{10, "H"}, {600, "A"}}, "Select Car", 1,
      {"lobby: list Waiting for players:@hp2host@hp2join1@hp2join2@hp2join3"
       "@hp2join4@hp2join5@hp2join6@hp2join7",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2@hp2join4"
       "@hp2join5@hp2join6@hp2join7@hp2join8",
       "lobby: start, 8 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // The hosted network goes, the console's wireless still on: the
    // notice, OK, the question.
    { "host_network_goes", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {250, "A"}}, "Local Wireless", 0,
      {"lobby: hosting", "lobby: the network went", "lobby: link down",
       WIRELESS_OFF_LINE, "lobby: ask"}, 150, 0, 0, 0, 0, 0, 0, 0, 0 },

    // The lobby left some other way than its own: the link down with it.
    { "host_away", 200, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {150, "X"}}, "Prev", 0,
      {"lobby: hosting", "lobby: link down"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "join_away", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {200, "X"}}, "Prev", 0,
      {"lobby: joined hp2host", "lobby: link down"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // Seven clients, two of which go before Start; the list follows, and
    // the five left get places 1 to 5 of 6.
    { "host_seven", 800, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}, {"hp2join2", 90, 360, 0}, {"hp2join3", 120, 0, 0},
       {"hp2join4", 150, 0, 0}, {"hp2join5", 180, 540, 0}, {"hp2join6", 210, 0, 0},
       {"hp2join7", 240, 0, 0}},
      NONE, 0, 0,
      {{10, "H"}, {700, "A"}}, "Select Car", 1,
      {"lobby: hosting",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2@hp2join3"
       "@hp2join4@hp2join5@hp2join6@hp2join7",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join3@hp2join4"
       "@hp2join5@hp2join6@hp2join7",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join3@hp2join4"
       "@hp2join6@hp2join7",
       "lobby: start, 6 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // The only client goes on the frame Start is pressed: nobody is told
    // to start, and the list stays up without it.
    { "host_client_goes", 250, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 150, 0}}, NONE, 0, 0,
      {{10, "H"}, {150, "A"}}, "Local Wireless", 1,
      {"lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: list Waiting for players:@hp2host"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // A client that comes after Start never gets in.
    { "host_late", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}, {"hp2join2", 250, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}}, "Select Car", 1,
      {"lobby: start, 2 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // No local wireless, or no network, the console's wireless on: a
    // notice, OK, the question again.
    { "host_no_wireless", 120, LANG_EN, 1, 0, 0, "hp2host", NONE, NONE,
      0, 0, {{10, "H"}, {60, "A"}}, "Local Wireless", 0,
      {"lobby: ask", WIRELESS_OFF_LINE, "lobby: ask"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "host_no_language", 120, -1, 1, 0, 0, "hp2host", NONE, NONE,
      0, 0, {{10, "H"}, {60, "A"}}, "Local Wireless", 0,
      {WIRELESS_OFF_LINE, "lobby: ask"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "host_fails", 120, LANG_EN, 0, 1, 0, "hp2host", NONE, NONE, 0, 0,
      {{10, "H"}, {60, "B"}}, "Local Wireless", 0,
      {"lobby: link down", WIRELESS_OFF_LINE, "lobby: ask"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "join_no_wireless", 120, LANG_EN, 1, 0, 0, "hp2join1", NONE, NONE,
      0, 0, {{10, "R"}, {20, "A"}, {60, "A"}}, "Local Wireless", 0,
      {WIRELESS_OFF_LINE, "lobby: ask"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // The console's wireless communication off (TASKS 62): Host or Join
    // says so, and that it is turned on from the HOME Menu, with UDS
    // never started; OK, the question.
    { "radio_off_host", 200, LANG_EN, 0, 0, 0, "hp2host", NONE, NONE,
      0, 0, {{10, "A"}, {60, "A"}, {100, "B"}}, "Prev", 0,
      {"lobby: ask", "lobby: wireless communication off", RADIO_OFF_LINE,
       "lobby: ask", "lobby: back"}, 0, 0, 0, 0, 1, 0, 0, 0, 0 },
    { "radio_off_join", 120, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {60, "A"}}, "Local Wireless", 0,
      {"lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 1, 0, 0, 0, 0 },
    // UDS would not start either: still the line that says why.
    { "radio_off_no_wireless", 120, LANG_EN, 1, 0, 0, "hp2host", NONE,
      NONE, 0, 0, {{10, "A"}, {60, "A"}}, "Local Wireless", 0,
      {RADIO_OFF_LINE, "lobby: ask"}, 0, 0, 0, 0, 1, 0, 0, 0, 0 },
    // French, and no language chosen yet: English.
    { "radio_off_french", 120, LANG_FR, 0, 0, 0, "hp2host", NONE, NONE,
      0, 0, {{10, "A"}}, "Local Wireless", 0,
      {"lobby: notice La communication sans fil est d\xe9sactiv\xe9" "e. "
       "Activez-la depuis le menu HOME pour jouer en sans fil local."},
      0, 0, 0, 0, 1, 0, 0, 0, 0 },
    { "radio_off_no_language", 120, -1, 0, 0, 0, "hp2host", NONE, NONE,
      0, 0, {{10, "A"}}, "Local Wireless", 0,
      {RADIO_OFF_LINE}, 0, 0, 0, 0, 1, 0, 0, 0, 0 },

    // Off, then turned on again: Host works.
    { "radio_back_on", 400, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 160, 0, 0}}, NONE, 0, 0,
      {{10, "A"}, {50, "A"}, {150, "H"}, {300, "A"}}, "Select Car", 1,
      {"lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask",
       "lobby: hosting", "lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: start, 2 consoles"}, 0, 0, 0, 0, 1, 100, 0, 0, 0 },

    // Turned off under the lobby with the link up: hosting, searching, a
    // race found, joined. The link goes and the line says why.
    { "radio_off_hosting", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {250, "A"}}, "Local Wireless", 0,
      {"lobby: hosting", "lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: link down", "lobby: wireless communication off",
       RADIO_OFF_LINE, "lobby: ask"}, 0, 0, 0, 0, 150, 0, 0, 0, 0 },
    { "radio_off_searching", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE, NONE,
      0, 0, {{10, "R"}, {20, "A"}, {250, "A"}}, "Local Wireless", 0,
      {"lobby: searching", "lobby: scan 0", "lobby: link down",
       "lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 150, 0, 0, 0, 0 },
    { "radio_off_found", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {250, "A"}}, "Local Wireless", 0,
      {"lobby: found 1 of 1, hp2host", "lobby: link down",
       "lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 150, 0, 0, 0, 0 },
    { "radio_off_joined", 400, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {300, "A"}}, "Local Wireless", 0,
      {"lobby: joined hp2host", "lobby: link down",
       "lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 200, 0, 0, 0, 0 },

    // Off on the frame of a press, before the lobby's tick and before the
    // network is seen to go: Join on a race found, Next past the last,
    // the host's Start. Nothing is asked of the link; the line says why.
    { "radio_off_press_join", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {150, "A"}, {250, "A"}}, "Local Wireless", 0,
      {"lobby: found 1 of 1, hp2host", "lobby: link down",
       "lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 150, 0, 0, 0, 0 },
    { "radio_off_press_next", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {100, "R"}, {150, "A"}, {250, "A"}},
      "Local Wireless", 0,
      {"lobby: found 1 of 1, hp2host", "lobby: link down",
       "lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 150, 0, 0, 0, 0 },
    { "radio_off_press_start", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {150, "A"}, {250, "A"}}, "Local Wireless", 0,
      {"lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: link down", "lobby: wireless communication off",
       RADIO_OFF_LINE, "lobby: ask"}, 0, 0, 0, 0, 150, 0, 0, 0, 0 },
    // B with it off: the question, as B always gives.
    { "radio_off_press_back", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {150, "B"}, {250, "B"}}, "Prev", 0,
      {"lobby: hosting", "lobby: link down", "lobby: ask", "lobby: back"},
      0, 0, 0, 0, 150, 0, 0, 0, 0 },

    // Turned off during the race's setup, which loses the host: back in
    // the lobby, the line says this console's wireless is off, not that
    // the link to the host was lost.
    { "radio_off_after_start", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {300, "N"}, {300, "CB"},
       {400, "A"}}, "Local Wireless", 0,
      {"lobby: started by hp2host, place 1 of 2", "lobby: link down",
       "lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 250, 0, 0, 0, 0 },
    // The same with it on: the race's own notice.
    { "radio_on_after_start", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {300, "N"}, {300, "CB"},
       {400, "A"}}, "Local Wireless", 0,
      {"lobby: started by hp2host, place 1 of 2", "lobby: link down",
       "lobby: notice The link to hp2host was lost.", "lobby: ask"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // A joiner: searching, a race found, Join, the host starts: on. The
    // host sends something else first, which is not a start.
    { "join_start", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 90, 0}}, 240, 0,
      {{10, "R"}, {20, "A"}, {200, "A"}}, "Select Car", 1,
      {"lobby: searching", "lobby: scan 0", "lobby: scan 1",
       "lobby: found 1 of 1, hp2host", "lobby: joined hp2host",
       "lobby: started by hp2host, place 1 of 2"}, 0, 1, 0, 0, 0, 0, 0, 0, 0 },

    // Ten seconds of nothing in range, and A pressed on it twice: a scan
    // a second, no more.
    { "join_nothing", 640, LANG_EN, 0, 0, 0, "hp2join1", NONE, NONE, 0, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {101, "A"}, {630, "B"}},
      "Local Wireless", 0,
      {"lobby: searching", "lobby: scan 0", "lobby: link down",
       "lobby: ask"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // Three races: Next walks them, the highlight staying on Next, then
    // scans again past the last.
    { "join_next", 400, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"Alice", 1, 8, 0, 0}, {"Bob", 3, 8, 0, 0}, {"Carol", 2, 4, 0, 0}},
      0, 0,
      {{10, "R"}, {20, "A"}, {100, "R"}, {110, "A"}, {150, "A"},
       {200, "A"}, {300, "B"}, {350, "B"}},
      "Prev", 0,
      {"lobby: found 1 of 3, Alice", "lobby: found 2 of 3, Bob",
       "lobby: found 3 of 3, Carol", "lobby: scan 3",
       "lobby: found 1 of 3, Alice", "lobby: link down", "lobby: ask",
       "lobby: back"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // Next once, B, and Join again: the first race again, not the second.
    { "join_next_back", 200, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"Alice", 1, 8, 0, 0}, {"Bob", 3, 8, 0, 0}, {"Carol", 2, 4, 0, 0}},
      0, 0,
      {{10, "R"}, {20, "A"}, {30, "R"}, {40, "A"}, {60, "B"}, {70, "R"},
       {80, "A"}},
      "Local Wireless", 1,
      {"lobby: found 2 of 3, Bob", "lobby: link down", "lobby: ask",
       "lobby: searching", "lobby: found 1 of 3, Alice"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // Next with nothing left in range: searching again.
    { "join_next_none", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 100}}, 0, 0,
      {{10, "R"}, {20, "A"}, {150, "R"}, {160, "A"}}, "Local Wireless", 1,
      {"lobby: found 1 of 1, hp2host", "lobby: scan 0",
       "lobby: searching"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // Joined, and the host goes: the link lost, OK, the question.
    { "join_lost", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 180,
      {{10, "R"}, {20, "A"}, {100, "A"}, {400, "A"}}, "Local Wireless", 0,
      {"lobby: joined hp2host", "lobby: lost hp2host", "lobby: link down",
       "lobby: notice The link to hp2host was lost.", "lobby: ask"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // A join refused: the notice, then searching again, the link still
    // up, with a scan at once although the last was a third of a second
    // before.
    { "join_refused", 300, LANG_EN, 0, 0, 1, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {30, "A"}, {40, "A"}}, "Local Wireless", 1,
      {"lobby: found 1 of 1, hp2host",
       "lobby: notice Could not join the race.", "lobby: searching",
       "lobby: found 1 of 1, hp2host"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // A and then B while waiting for the host: off the network and asked
    // again.
    { "join_leave", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {150, "A"}, {200, "B"}},
      "Local Wireless", 0,
      {"lobby: joined hp2host", "lobby: link down", "lobby: ask"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // The race found goes out of range before Join: refused.
    { "join_gone", 300, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 90}}, 0, 0,
      {{10, "R"}, {20, "A"}, {150, "A"}}, "Local Wireless", 1,
      {"lobby: found 1 of 1, hp2host",
       "lobby: notice Could not join the race."}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // B on car select comes back to the lobby, which takes the link down.
    { "host_back_from_cars", 400, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "CB"}}, "Local Wireless", 0,
      {"lobby: start, 2 consoles", "lobby: link down", "lobby: ask"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "join_back_from_cars", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {300, "CB"}, {400, "B"}},
      "Prev", 0,
      {"lobby: started by hp2host, place 1 of 2", "lobby: link down",
       "lobby: ask", "lobby: back"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // French, and names past ASCII: Latin-1 bytes, '?' for the rest, for
    // '@' and for each sequence cut short or byte out of place.
    { "host_french", 300, LANG_FR, 0, 0, 0, "Zo\xc3\xab",
      {{"J\xc3\xbcrgen", 60, 0, 0}, {"a@b\xe2\x82\xac", 72, 0, 0},
       {"x\xc3y\x80z\xe9!", 84, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {250, "B"}}, "Local Wireless", 0,
      {"lobby: list En attente de joueurs :@Zo\xeb@J\xfcrgen@a?b?"
       "@x?y?z?!"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "join_french", 300, LANG_FR, 0, 0, 0, "hp2join1", NONE,
      {{"Andr\xc3\xa9", 3, 8, 0, 0}}, 0, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}}, "Local Wireless", 1,
      {"lobby: found 1 of 1, Andr\xe9", "lobby: joined Andr\xe9"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },

    // The CPU racers (TASKS 37c-2). A Full Grid: as many as fit, CPU Racers
    // alone until a client comes, then Start first.
    { "cpu_full", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}}, "Select Car", 1,
      {"lobby: list Waiting for players:@hp2host@CPU racers: 7",
       "lobby: list Waiting for players:@hp2host@hp2join1@CPU racers: 6",
       "lobby: start, 2 consoles, 6 CPU racers"}, 0, 0, 1, LOBBY_CPU_FULL, 0, 0, 0, 0, 0 },

    // None to begin with (a Single Race with the cops). A counts on, and
    // the highlight stays on CPU Racers when a client comes; past the six
    // that fit beside two consoles, none again. Left to Start, and a
    // second client puts the list up with Start highlighted.
    { "cpu_cycle", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}, {"hp2join2", 180, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {30, "A"}, {40, "A"}, {100, "A"}, {110, "A"}, {120, "A"},
       {130, "A"}, {140, "A"}, {160, "L"}, {220, "A"}}, "Select Car", 1,
      {"lobby: list Waiting for players:@hp2host@CPU racers: 0",
       "lobby: cpu 1", "lobby: cpu 2",
       "lobby: list Waiting for players:@hp2host@hp2join1@CPU racers: 2",
       "lobby: cpu 3", "lobby: cpu 4", "lobby: cpu 5", "lobby: cpu 6",
       "lobby: cpu 0",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@CPU racers: 0",
       "lobby: start, 3 consoles, 0 CPU racers"}, 0, 0, 1, 0, 0, 0, 0, 0, 0 },

    // Four wished and one counted on: as many of the five as fit while
    // clients come, no line or CPU Racers with eight consoles, and the
    // five again as they go. A on CPU Racers as the eighth comes counts
    // nothing, and the highlight is back on CPU Racers once there is room.
    { "cpu_clamp", 600, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}, {"hp2join2", 70, 0, 0}, {"hp2join3", 80, 0, 0},
       {"hp2join4", 90, 400, 0}, {"hp2join5", 100, 420, 0},
       {"hp2join6", 110, 440, 0}, {"hp2join7", 300, 0, 0}},
      NONE, 0, 0,
      {{10, "H"}, {40, "A"}, {300, "A"}, {550, "A"}},
      "Local Wireless", 1,
      {"lobby: list Waiting for players:@hp2host@CPU racers: 4",
       "lobby: cpu 5",
       "lobby: list Waiting for players:@hp2host@hp2join1@CPU racers: 5",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@hp2join3@hp2join4@CPU racers: 3",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@hp2join3@hp2join4@hp2join5@hp2join6@CPU racers: 1",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@hp2join3@hp2join4@hp2join5@hp2join6@hp2join7",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@hp2join3@hp2join5@hp2join6@hp2join7@CPU racers: 1",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@hp2join3@hp2join7@CPU racers: 3",
       "lobby: cpu 0",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@hp2join3@hp2join7@CPU racers: 0"}, 0, 0, 1, 4, 0, 0, 0, 0, 0 },

    // No choice for the mode: the list and Start as without a wish.
    { "cpu_none", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}}, "Select Car", 1,
      {"lobby: list Waiting for players:@hp2host",
       "lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: start, 2 consoles"}, 0, 0, 1, LOBBY_CPU_NONE, 0, 0, 0, 0, 0 },

    // Counted on, then B and Host again: the wish again, the highlight on
    // Start once a client comes.
    { "cpu_rehost", 300, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 150, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {30, "A"}, {50, "B"}, {80, "H"}, {250, "A"}},
      "Select Car", 1,
      {"lobby: list Waiting for players:@hp2host@CPU racers: 2",
       "lobby: cpu 3", "lobby: link down", "lobby: hosting",
       "lobby: list Waiting for players:@hp2host@CPU racers: 2",
       "lobby: list Waiting for players:@hp2host@hp2join1@CPU racers: 2",
       "lobby: start, 2 consoles, 2 CPU racers"}, 0, 0, 1, 2, 0, 0, 0, 0, 0 },

    // French.
    { "cpu_french", 300, LANG_FR, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {100, "R"}, {120, "A"}, {200, "B"}}, "Local Wireless", 0,
      {"lobby: list En attente de joueurs :@hp2host@hp2join1"
       "@Pilotes IA : 6",
       "lobby: cpu 0",
       "lobby: list En attente de joueurs :@hp2host@hp2join1"
       "@Pilotes IA : 0"}, 0, 0, 1, LOBBY_CPU_FULL, 0, 0, 0, 0, 0 },

    // Back from the race (TASKS 37f). The host's list without the client
    // until it says it is back, then with it and Start; the next race.
    { "host_race_back", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 30}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {400, "A"}}, "Select Car", 1,
      {"lobby: start, 2 consoles",
       "lobby: back from the race, hosting, 1 to come",
       "lobby: list Waiting for players:@hp2host",
       "lobby: hp2join1 is back", "lobby: every console back",
       "lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: start, 2 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // One never back: no Start, the race's timeout kept, until it goes.
    { "host_race_back_never", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 450, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {400, "A"}}, "Local Wireless", 1,
      {"lobby: back from the race, hosting, 1 to come",
       "lobby: every console back"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // Two back, the race's last first from each; a third joins the open
    // network after the race, listed at once; four in the next race.
    { "host_race_back_two", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 60}, {"hp2join2", 70, 0, 20},
       {"hp2join3", 380, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {450, "A"}}, "Select Car", 1,
      {"lobby: start, 3 consoles",
       "lobby: back from the race, hosting, 2 to come",
       "lobby: hp2join2 is back",
       "lobby: list Waiting for players:@hp2host@hp2join2",
       "lobby: hp2join1 is back", "lobby: every console back",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2",
       "lobby: list Waiting for players:@hp2host@hp2join1@hp2join2"
       "@hp2join3",
       "lobby: start, 4 consoles"}, 0, 1, 0, 0, 0, 0, 0, 0, 0 },
    // The first never back and gone, the second back: its place taken
    // by the second, which is back.
    { "host_race_back_goes", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 340, 0}, {"hp2join2", 70, 0, 20}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {400, "A"}}, "Select Car", 1,
      {"lobby: back from the race, hosting, 2 to come",
       "lobby: hp2join2 is back",
       "lobby: list Waiting for players:@hp2host@hp2join2",
       "lobby: every console back", "lobby: start, 2 consoles"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // The network gone during the race, or the console's wireless off:
    // the line that says so, OK, the question.
    { "host_race_back_network_went", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 30}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {400, "A"}}, "Local Wireless", 0,
      {"lobby: start, 2 consoles",
       "lobby: back from the race, the network went", "lobby: link down",
       WIRELESS_OFF_LINE, "lobby: ask"}, 250, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "host_race_back_radio_off", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 30}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {400, "A"}}, "Local Wireless", 0,
      {"lobby: back from the race, wireless communication off",
       "lobby: wireless communication off", RADIO_OFF_LINE, "lobby: ask"},
      0, 0, 0, 0, 250, 0, 0, 0, 0 },
    // A joiner: the wait for the host, the race's last passed over, the
    // host back, its next Start; B on car select then is only that.
    { "join_race_back", 600, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {300, "RB"}, {500, "CB"}},
      "Local Wireless", 0,
      {"lobby: started by hp2host, place 1 of 2",
       "lobby: back from the race, waiting for hp2host",
       "lobby: hp2host is back", "lobby: every console back",
       "lobby: started by hp2host, place 1 of 2", "lobby: link down",
       "lobby: ask"},
      0, 1, 0, 0, 0, 0, 0, 20, 100 },
    // The host lost during the race, or while it is awaited.
    { "join_race_back_lost", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 150,
      {{10, "R"}, {20, "A"}, {100, "A"}, {300, "RB"}, {400, "A"}},
      "Local Wireless", 0,
      {"lobby: started by hp2host, place 1 of 2",
       "lobby: back from the race, hp2host lost", "lobby: link down",
       "lobby: notice The link to hp2host was lost.", "lobby: ask"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },
    { "join_race_back_host_goes", 600, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 300,
      {{10, "R"}, {20, "A"}, {100, "A"}, {300, "RB"}, {500, "A"}},
      "Local Wireless", 0,
      {"lobby: back from the race, waiting for hp2host",
       "lobby: lost hp2host", "lobby: link down",
       "lobby: notice The link to hp2host was lost.", "lobby: ask"},
      0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // The race's own notice wins over the return: the link down.
    { "join_race_back_notice", 500, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {290, "N"}, {300, "RB"},
       {400, "A"}}, "Local Wireless", 0,
      {"lobby: started by hp2host, place 1 of 2", "lobby: link down",
       "lobby: notice The link to hp2host was lost.", "lobby: ask"},
      0, 0, 0, 0, 0, 0, 0, 20, 0 },
    // The same, then a race joined again and B on car select: the link
    // down, with no return left over from the first.
    { "join_race_back_notice_cb", 700, LANG_EN, 0, 0, 0, "hp2join1", NONE,
      {{"hp2host", 1, 8, 0, 0}}, 60, 0,
      {{10, "R"}, {20, "A"}, {100, "A"}, {290, "N"}, {300, "RB"},
       {400, "A"}, {410, "R"}, {420, "A"}, {500, "A"}, {600, "CB"}},
      "Local Wireless", 0,
      {"lobby: started by hp2host, place 1 of 2", "lobby: link down",
       "lobby: notice The link to hp2host was lost.", "lobby: ask",
       "lobby: joined hp2host", "lobby: started by hp2host, place 1 of 2",
       "lobby: link down", "lobby: ask"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // The host's B with a client awaited, and Host again: the client
    // listed as it comes, Start at once.
    { "host_race_back_rehost", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {350, "B"}, {370, "H"},
       {450, "A"}}, "Select Car", 1,
      {"lobby: back from the race, hosting, 1 to come", "lobby: link down",
       "lobby: list Waiting for players:@hp2host@hp2join1",
       "lobby: start, 2 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
    // The first gone while both are awaited: the second, awaited, takes
    // its place; once it is back, a third that comes is listed at once.
    { "host_race_back_compact", 500, LANG_EN, 0, 0, 0, "hp2host",
      {{"hp2join1", 60, 320, 0}, {"hp2join2", 70, 0, 60},
       {"hp2join3", 380, 0, 0}}, NONE, 0, 0,
      {{10, "H"}, {200, "A"}, {300, "RB"}, {450, "A"}}, "Select Car", 1,
      {"lobby: start, 3 consoles",
       "lobby: back from the race, hosting, 2 to come",
       "lobby: list Waiting for players:@hp2host",
       "lobby: hp2join2 is back", "lobby: every console back",
       "lobby: list Waiting for players:@hp2host@hp2join2",
       "lobby: list Waiting for players:@hp2host@hp2join2@hp2join3",
       "lobby: start, 3 consoles"}, 0, 0, 0, 0, 0, 0, 0, 0, 0 },
};
#define NUM_SCENARIOS ((int)(sizeof kScenarios / sizeof kScenarios[0]))

// ------------------------------------------------------------ the fake

static const Scenario* S;
static int             g_faults;
static int             g_frame;
static BGameFlow       g_gf;

static struct {
    int      up, network, host, open, lost;
    // hosting: each client's place in the order it came
    int      came[MAX_CLIENTS];        // by S->clients
    int      order[MAX_CLIENTS];       // by place: which client
    int      alive[MAX_CLIENTS];
    int      starts[MAX_CLIENTS];      // LOBBY_MSG_STARTs sent
    uint8_t  startMsg[MAX_CLIENTS][4];
    int      numPeers;
    // joining
    int      scanRace[MAX_RACES];      // the last scan's: which race
    int      numScan;
    int      joined;                   // the race, or -1
    int      joinedAt;                 // the frame
    int      startQueued, startRead, junkRead;
    uint32_t lastScanMs;
    int      scans;
    int      searchBegan;              // a new search, not yet scanned
    int      nextAsked;                // A on Next this frame
    // hosting: the CPU racers wished (-1 no choice), the highlight on CPU
    // Racers, and the lobby's starts
    int      want, onCpu, raceStarts;
    // the setup as lobby_on_setup last told it, and the cops as the
    // flow's police hook last did
    int      setupOn, cops;
    // back from the race (37f): in it (gameflow's raceReturn asks), back
    // and on which frame; by client, whether it raced, the host's
    // LOBBY_MSG_BACKs to it and its own read; a joiner's sent, and the
    // host's read; the link's timeout as last set, 0 its own
    int      racing, returned, returnFrame;
    int      raced[MAX_CLIENTS], backsTo[MAX_CLIENTS], backRead[MAX_CLIENTS];
    int      joinerBacks, hostBackRead;
    int      junkFrom[MAX_CLIENTS];
    uint32_t patience;
} N;

static void fault(const char* fmt, ...)
{
    va_list ap;
    printf("  FAULT frame %d: ", g_frame);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    g_faults++;
}

static uint32_t lobbyMs(void)
{
    return g_gf.realTimer / 4;   // the lobby's clock
}

static int inRange(const Race* r)
{
    return r->name && g_frame >= r->from
        && (r->until == 0 || g_frame < r->until);
}

// The console's wireless communication off (TASKS 62). The network it
// takes down is seen to go RADIO_LAG frames later, as UDS's status lags
// the shared page.
#define RADIO_LAG 2

static int radioIsOff(void)
{
    return S->radioOffFrom && g_frame >= S->radioOffFrom
        && (S->radioOffUntil == 0 || g_frame < S->radioOffUntil);
}

static int fRadioOff(void)
{
    return radioIsOff();
}

static void radioFault(const char* call)
{
    if (radioIsOff()) fault("%s with the wireless off", call);
}

static int fStart(void)
{
    printf("net start\n");
    radioFault("start");
    N.patience = 0;   // wireless_start clears the link's timeout
    if (S->noWireless || radioIsOff()) return 0;
    N.up = 1;
    return 1;
}

static void fStop(void)
{
    printf("net stop\n");
    if (N.network) fault("stop while on a network");
    N.up = 0;
}

static int fHost(int consoles, const void* appdata, size_t n)
{
    (void)appdata;
    printf("net host %d %u\n", consoles, (unsigned)n);
    radioFault("host");
    if (!N.up || N.network) fault("host with up %d network %d", N.up,
                                  N.network);
    if (!N.up || N.network || S->hostFails) return 0;
    if (consoles != WIRELESS_MAX_CONSOLES) fault("host for %d", consoles);
    N.network = 1;
    N.host    = 1;
    N.open    = 1;
    return 1;
}

static void fSetOpen(int open)
{
    printf("net open %d\n", open);
    radioFault("setOpen");
    if (!N.host) fault("setOpen with no network of ours");
    N.open = open;
}

static int fScan(WirelessHost* out, int max)
{
    int      i, n = 0;
    uint32_t now = lobbyMs();

    printf("net scan\n");
    radioFault("scan");
    if (!N.up || N.network) fault("scan with up %d network %d", N.up,
                                  N.network);
    if (N.scans > 0 && !N.nextAsked && !N.searchBegan
        && now - N.lastScanMs < LOBBY_SCAN_MS)
        fault("a scan %u ms after the last", (unsigned)(now - N.lastScanMs));
    N.scans++;
    N.lastScanMs  = now;
    N.searchBegan = 0;
    N.numScan     = 0;
    for (i = 0; i < MAX_RACES && n < max; i++) {
        const Race* r = &S->races[i];
        if (!inRange(r)) continue;
        memset(&out[n], 0, sizeof out[n]);
        snprintf(out[n].name, sizeof out[n].name, "%s", r->name);
        out[n].consoles    = r->consoles;
        out[n].maxConsoles = r->max;
        out[n].scanIndex   = n + 10;   // the scan's own index, not the list's
        N.scanRace[n]      = i;
        n++;
    }
    N.numScan = n;
    return n;
}

static int fJoin(int scanIndex)
{
    int k = scanIndex - 10;

    printf("net join %d\n", scanIndex);
    radioFault("join");
    if (!N.up || N.network) fault("join with up %d network %d", N.up,
                                  N.network);
    if (k < 0 || k >= N.numScan) {
        fault("join of scan index %d, not the last scan's", scanIndex);
        return 0;
    }
    if (S->joinFails || !inRange(&S->races[N.scanRace[k]])) return 0;
    N.network     = 1;
    N.host        = 0;
    N.lost        = 0;
    N.joined      = N.scanRace[k];
    N.joinedAt    = g_frame;
    N.startQueued = N.startRead = N.junkRead = 0;
    return 1;
}

static void fLeave(void)
{
    printf("net leave\n");
    N.network = N.host = N.open = N.lost = 0;
    N.numPeers = 0;
    memset(N.came, 0, sizeof N.came);
    N.joined = -1;
    N.returned = 0;   // a later network's consoles never raced
}

static WirelessState fState(void)
{
    if (!N.up) return WIRELESS_OFF;
    if (!N.network) return WIRELESS_IDLE;
    if (N.host) return WIRELESS_HOSTING;
    return N.lost ? WIRELESS_LOST : WIRELESS_CONNECTED;
}

static int fPeerCount(void)
{
    return N.network ? (N.host ? N.numPeers : 1) : 0;
}

static int fPeerAlive(int i)
{
    if (!N.network) return 0;
    if (!N.host) return i == 0 && !N.lost;
    return i >= 0 && i < N.numPeers && N.alive[i];
}

static const char* fPeerName(int i)
{
    if (!N.network) return "";
    if (!N.host) return N.joined >= 0 ? S->races[N.joined].name : "";
    return i >= 0 && i < N.numPeers ? S->clients[N.order[i]].name : "";
}

static void fForgetLost(void)
{
    int i, j = 0;

    printf("net forget\n");
    if (!N.host) fault("forgetLost not hosting");
    for (i = 0; i < N.numPeers; i++) {
        if (!N.alive[i]) continue;
        N.order[j]  = N.order[i];
        N.alive[j]  = 1;
        N.starts[j] = N.starts[i];
        memcpy(N.startMsg[j], N.startMsg[i], 4);
        j++;
    }
    N.numPeers = j;
}

static const char* fSelfName(void)
{
    return N.network ? S->self : "";
}

static int fSend(int i, uint8_t type, const void* data, size_t n)
{
    printf("net send %d %02x %u\n", i, (unsigned)type, (unsigned)n);
    radioFault("send");
    if (!N.host) {
        // A joiner's one message: that it is back from the race.
        if (type != LOBBY_MSG_BACK || i != 0 || !fPeerAlive(0)) {
            fault("a joiner's send of %02x to %d", (unsigned)type, i);
            return 0;
        }
        if (!N.returned) fault("back with no race");
        if (++N.joinerBacks > 1) fault("back said %d times", N.joinerBacks);
        return 1;
    }
    if (!fPeerAlive(i)) {
        fault("send to %d, not a client still on", i);
        return 0;
    }
    if (type == LOBBY_MSG_BACK) {
        int c = N.order[i];

        if (!N.returned || !N.raced[c]) fault("back to %d, not raced", i);
        if (n != 1) fault("a back of %u bytes", (unsigned)n);
        if (++N.backsTo[c] > 1)
            fault("back said to %d %d times", i, N.backsTo[c]);
        return 1;
    }
    if (type == LOBBY_MSG_START) {
        N.starts[i]++;
        if (n != 4) fault("a start of %u bytes", (unsigned)n);
        else memcpy(N.startMsg[i], data, 4);
    }
    return 1;
}

// A client back from the race and not yet read as back.
static int awaitedClient(int c)
{
    return N.returned && N.raced[c] && !N.backRead[c];
}

// A client's, to the host: after the race's return, the race's last
// first (junkFirst), then that it is back, as the script has it.
static int hostRecv(int i, WlMsg* out)
{
    int c;

    if (!N.network || i < 0 || i >= N.numPeers || !N.alive[i]) return 0;
    c = N.order[i];
    if (!N.returned || !N.raced[c]) return 0;
    memset(out, 0, sizeof *out);
    if (S->junkFirst && !N.junkFrom[c]) {
        out->type     = 0x16;   // netstep's PADS, its stop again
        out->len      = 19;
        N.junkFrom[c] = 1;
        printf("net recv junk from %s\n", S->clients[c].name);
        return 1;
    }
    if (!S->clients[c].backAfter || N.backRead[c]
        || g_frame - N.returnFrame < S->clients[c].backAfter)
        return 0;
    out->type      = LOBBY_MSG_BACK;
    out->len       = 1;
    N.backRead[c]  = 1;
    printf("net recv back from %s\n", S->clients[c].name);
    return 1;
}

static int fRecv(int i, WlMsg* out)
{
    if (N.host) return hostRecv(i, out);
    if (!N.network || N.lost || i != 0) return 0;
    if (S->junkFirst && !N.junkRead) {
        // Something of a later step's, which the lobby must pass over.
        memset(out, 0, sizeof *out);
        out->type   = 0x55;
        out->len    = 4;
        N.junkRead  = 1;
        printf("net recv junk\n");
        return 1;
    }
    if (N.returned && S->hostBackAfter && !N.hostBackRead
        && g_frame - N.returnFrame >= S->hostBackAfter) {
        memset(out, 0, sizeof *out);
        out->type       = LOBBY_MSG_BACK;
        out->len        = 1;
        N.hostBackRead  = 1;
        printf("net recv back\n");
        return 1;
    }
    if (!N.startQueued || N.startRead) return 0;
    memset(out, 0, sizeof *out);
    out->type    = LOBBY_MSG_START;
    out->len     = S->shortStart ? 2 : 4;
    out->data[0] = 2;
    out->data[1] = 1;
    out->data[2] = HOST_GAME_TYPE;
    out->data[3] = 1;   // the cops on
    N.startRead  = 1;
    printf("net recv start\n");
    return 1;
}

// The lobby's only: the link's own timeout again, once each console still
// on is back from the race.
static void fSetPatience(uint32_t ms)
{
    printf("net patience %u\n", (unsigned)ms);
    if (ms != 0) fault("the lobby's patience %u", (unsigned)ms);
    if (!N.returned) fault("the patience set with no race");
    else if (N.patience == 0) fault("the link's own timeout given back again");
    N.patience = ms;
}

static const LobbyNet kNet = {
    fStart, fStop, fHost, fSetOpen, fScan, fJoin, fLeave, fState,
    fPeerCount, fPeerAlive, fPeerName, fForgetLost, fSelfName, fSend, fRecv,
    fRadioOff, fSetPatience,
};

// The script moves on to this frame: clients come and go, and a joined
// host starts or goes.
static void fakeStep(void)
{
    int c, radioDrop = radioIsOff()
                    && g_frame >= S->radioOffFrom + RADIO_LAG;

    if (radioIsOff() && g_frame == S->radioOffFrom)
        printf("net wireless off\n");
    if (S->radioOffUntil && g_frame == S->radioOffUntil)
        printf("net wireless on\n");
    if (N.network && N.host
        && ((S->hostDropAt && g_frame >= S->hostDropAt) || radioDrop)) {
        // UDS stays up, on no network.
        N.network = N.host = N.open = 0;
        N.numPeers = 0;
        memset(N.came, 0, sizeof N.came);
        printf("net network went\n");
    }
    if (N.network && !N.host && !N.lost && radioDrop) {
        N.lost = 1;
        printf("net host lost to the wireless off\n");
    }
    if (N.network && N.host) {
        for (c = 0; c < MAX_CLIENTS; c++) {
            const Client* cl = &S->clients[c];
            if (!cl->name || N.came[c] || !N.open) continue;
            if (g_frame < cl->joinAt) continue;
            if (cl->leaveAt && g_frame >= cl->leaveAt) continue;
            // A place kept for one that went is still taken (wireless.c).
            if (N.numPeers >= WIRELESS_MAX_PEERS) continue;
            N.came[c]             = 1;
            N.order[N.numPeers]   = c;
            N.alive[N.numPeers]   = 1;
            N.starts[N.numPeers]  = 0;
            N.numPeers++;
            printf("net client %s came\n", cl->name);
        }
        for (c = 0; c < N.numPeers; c++) {
            const Client* cl = &S->clients[N.order[c]];
            if (N.alive[c] && cl->leaveAt && g_frame >= cl->leaveAt) {
                N.alive[c] = 0;
                printf("net client %s went\n", cl->name);
            }
        }
    }
    if (N.network && !N.host && !N.lost) {
        if (S->lostAfter && g_frame - N.joinedAt >= S->lostAfter) {
            N.lost = 1;
            printf("net host went\n");
        }
        if (S->startAfter && !N.startQueued && !N.returned
            && g_frame - N.joinedAt >= S->startAfter) {
            N.startQueued = 1;
            printf("net host started\n");
        }
        if (S->restartAfter && !N.startQueued && N.returned
            && g_frame - N.returnFrame >= S->restartAfter) {
            N.startQueued = 1;
            printf("net host started again\n");
        }
    }
}

// ------------------------------------------------------------- the flow

static int         g_soundThisFrame;
static int         g_pressThisFrame;
static int         g_sounds[8];   // during a press
static int         g_numSounds;
static const char* g_entered;   // a screen entered this frame

// The popups summoned this frame, and the one up at the end of the last.
static int g_summons;
static struct {
    int     up, numButtons;
    int32_t button[3];
    uint32_t current;
    char    message[600];
} g_last;

static void wTrace(void* user, const char* line)
{
    (void)user;
    printf("%s\n", line);
    if (!strncmp(line, "popup ", 6) && strstr(line, " summon")) g_summons++;
}

static const BPopup* upPopup(int* count);

// A popup up again with nothing changed blinks on the screen: only a
// press, or what it says or offers changing, puts one up.
static void checkAgain(void)
{
    int           n;
    const BPopup* p = upPopup(&n);
    const char*   msg = p && p->cfg.message ? p->cfg.message : "";

    if (p && g_summons && !g_pressThisFrame && g_last.up
        && g_last.numButtons == p->cfg.numButtons
        && !memcmp(g_last.button, p->cfg.button, sizeof g_last.button)
        && g_last.current == p->current && !strcmp(g_last.message, msg))
        fault("the popup put up again as it was");
    g_last.up = p != NULL;
    if (!p) return;
    g_last.numButtons = p->cfg.numButtons;
    memcpy(g_last.button, p->cfg.button, sizeof g_last.button);
    g_last.current = p->current;
    snprintf(g_last.message, sizeof g_last.message, "%s", msg);
}

static void wSound(void* user, int ev)
{
    (void)user;
    printf("sound %d\n", ev);
    g_soundThisFrame++;
    if (g_numSounds < 8) g_sounds[g_numSounds] = ev;
    g_numSounds++;
}

static void otherScreen(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data)
{
    (void)data;
    if (msg == BMSG_SCREEN_ACTIVATE) g_entered = gf->screen->name;
}

// The host's setup screens: the Challenge, and the Setup it can go to.
#define SINGLE_RACE_SETUP "Single Race Setup"

static const BScreenConfig kScreens[] = {
    { "Prev",             0x11111111u, otherScreen },
    { LOBBY_SCREEN_NAME,  0,           lobby_callback },
    { LOBBY_NEXT_SCREEN,  0x22222222u, otherScreen },
    { LOBBY_SETUP_SCREEN, 0x33333333u, otherScreen },
    { SINGLE_RACE_SETUP,  0x44444444u, otherScreen },
};

static int onSetup(void)
{
    return g_gf.screen && (!strcmp(g_gf.screen->name, LOBBY_SETUP_SCREEN)
                           || !strcmp(g_gf.screen->name, SINGLE_RACE_SETUP));
}

static const BGameFlowStateInfo kStates[BGF_NUM_STATES] = {
    { "NONE",                     NULL, NULL, NULL },
    { "LOADING_FRONTEND",         NULL, NULL, NULL },
    { "UNLOADING_FRONTEND",       NULL, NULL, NULL },
    { "IN_FRONTEND",              NULL, NULL, NULL },
    { "LOADING_TRACK_COMMON",     NULL, NULL, NULL },
    { "LOADING_TRACK_SPECIFIC",   NULL, NULL, NULL },
    { "RACING",                   NULL, NULL, NULL },
    { "UNLOADING_TRACK_SPECIFIC", NULL, NULL, NULL },
    { "UNLOADING_TRACK_COMMON",   NULL, NULL, NULL },
};

// --------------------------------------------------------------- checks

#define LOG_MAX 256

static char g_log[LOG_MAX][600];
static int  g_numLog;

static void wLog(const char* line)
{
    printf("%s\n", line);
    // Each hosting asks the wish again, the highlight where Start is.
    if (!strcmp(line, "lobby: hosting")) {
        N.want  = S->cpuFn && S->cpuWish >= 0 ? S->cpuWish : -1;
        N.onCpu = 0;
    }
    // A search begun on a scan that found nothing (Next past the last)
    // waits its second; any other scans at once.
    if (!strcmp(line, "lobby: searching"))
        N.searchBegan = g_numLog == 0
                     || strncmp(g_log[g_numLog - 1], "lobby: scan ", 12);
    if (g_numLog < LOG_MAX) {
        snprintf(g_log[g_numLog], sizeof g_log[0], "%s", line);
        g_numLog++;
    }
}

static const char* text(int32_t id)
{
    const char* s = portlang_get(S->language >= 0 ? S->language : LANG_EN,
                                 id, NULL);
    return s ? s : "";
}

static const BPopup* upPopup(int* count)
{
    const BPopup* p = NULL;
    int           i;
    *count = 0;
    for (i = 0; i < BPOPUP_COUNT; i++) {
        if (!g_gf.popups[i].active) continue;
        (*count)++;
        p = &g_gf.popups[i];
    }
    return p;
}

static int onLobby(void)
{
    return g_gf.screen && !strcmp(g_gf.screen->name, LOBBY_SCREEN_NAME);
}

static void append(char* out, size_t cap, const char* utf8)
{
    char name[WIRELESS_NAME_MAX];
    lobby_latin1(name, sizeof name, utf8);
    strncat(out, "@", cap - strlen(out) - 1);
    strncat(out, name, cap - strlen(out) - 1);
}

// The room on the grid beside the host and the clients still on.
static int room(void)
{
    int i, n = LOBBY_GRID - 1;
    for (i = 0; i < N.numPeers; i++) n -= N.alive[i] != 0;
    return n;
}

// The CPU racers the host's list must show: as many as wished of those
// that fit, -1 for no line.
static int cpuWanted(void)
{
    if (N.want < 0 || room() <= 0) return -1;
    return N.want < room() ? N.want : room();
}

static void checkFrame(void)
{
    int           n;
    const BPopup* p   = upPopup(&n);
    const char*   msg = p && p->cfg.message ? p->cfg.message : "";

    if (n > 1) fault("%d popups up", n);
    if (!onLobby()) {
        if (n) fault("a popup up off the lobby");
    } else {
        if (!p) {
            fault("the lobby with no popup");
            return;
        }
        if (!p->parentName || strcmp(p->parentName, LOBBY_SCREEN_NAME))
            fault("the popup's parent is %s",
                  p->parentName ? p->parentName : "-");
        if (!strcmp(msg, text(PORTLANG_HOST_OR_JOIN)) && N.up)
            fault("the question with the link up");
        if (!strcmp(msg, text(PORTLANG_HOST_MODE))) {
            if (N.up) fault("the mode asked with the link up");
            if (p->cfg.numButtons != 2 || p->cfg.button[0] != 10023
                || p->cfg.button[1] != 10022)
                fault("the mode's buttons are %d: %d and %d",
                      p->cfg.numButtons, p->cfg.button[0],
                      p->cfg.button[1]);
        }
    }
    if (N.setupOn != onSetup())
        fault("the setup told %d on %s", N.setupOn,
              g_gf.screen ? g_gf.screen->name : "-");
    if (onSetup() && N.up) fault("the setup with the link up");

    if (onLobby() && p && N.network && N.host) {
        char        want[600];
        int         i, alive = 0, cpu = cpuWanted(), buttons, lines = 1;
        int         waiting = 0;
        const char* c;
        snprintf(want, sizeof want, "%s", text(PORTLANG_WAITING_FOR_PLAYERS));
        append(want, sizeof want, S->self);
        // Back from the race, a client is listed once it says so, and
        // Start waits for every one.
        for (i = 0; i < N.numPeers; i++) {
            if (!N.alive[i]) continue;
            if (awaitedClient(N.order[i])) {
                waiting++;
                continue;
            }
            alive++;
            append(want, sizeof want, S->clients[N.order[i]].name);
        }
        if (waiting) alive = 0;
        if (cpu >= 0) {
            const char* t  = text(PORTLANG_CPU_RACERS_N);
            const char* at = strstr(t, "$N");
            char        line[64];
            snprintf(line, sizeof line, "%.*s%d%s", (int)(at - t), t, cpu,
                     at + 2);
            strncat(want, "@", sizeof want - strlen(want) - 1);
            strncat(want, line, sizeof want - strlen(want) - 1);
        }
        if (strcmp(msg, want)) fault("the host's popup says \"%s\"", msg);
        // The memory card's popup screen has nine lines.
        for (c = msg; *c; c++) lines += *c == '@';
        if (lines > 9) fault("the host's popup has %d lines", lines);
        // Start once there is a client, then CPU Racers; the highlight on
        // CPU Racers once A counted there, until a move to Start.
        buttons = cpu < 0 ? alive > 0 : alive > 0 ? 2 : 1;
        if (p->cfg.numButtons != buttons) {
            fault("%d buttons with %d clients and %d CPU racers",
                  p->cfg.numButtons, alive, cpu);
        } else if (buttons == 2) {
            if (p->cfg.button[0] != PORTLANG_START
                || p->cfg.button[1] != PORTLANG_CPU_RACERS)
                fault("the buttons are %d and %d", p->cfg.button[0],
                      p->cfg.button[1]);
            else if ((int)(p->current % 2) != N.onCpu)
                fault("the highlight on %s",
                      p->current % 2 ? "CPU Racers" : "Start");
        } else if (buttons == 1
                   && p->cfg.button[0]
                      != (cpu < 0 ? PORTLANG_START : PORTLANG_CPU_RACERS)) {
            fault("the button is %d", p->cfg.button[0]);
        }
    }
    if (onLobby() && p && N.network && !N.host && !N.lost) {
        char        name[WIRELESS_NAME_MAX], want[600];
        const char* t  = text(PORTLANG_WAITING_FOR_HOST);
        const char* at = strstr(t, "$NAME");
        lobby_latin1(name, sizeof name, S->races[N.joined].name);
        snprintf(want, sizeof want, "%.*s%s%s", (int)(at - t), t, name,
                 at + 5);
        if (strcmp(msg, want)) fault("the joiner's popup says \"%s\"", msg);
    }
    if (g_soundThisFrame && !g_pressThisFrame)
        fault("a sound with no press");
    if (N.searchBegan) fault("a search begun with no scan");
}

// After the lobby's tick, back from the race with the link up: the race's
// timeout while a console still on has yet to say it is back, the link's
// own once none has.
static void checkPatience(void)
{
    int i, waiting = 0;

    if (!N.returned || !onLobby() || !N.network) return;
    if (N.host) {
        for (i = 0; i < N.numPeers; i++)
            waiting += N.alive[i] && awaitedClient(N.order[i]);
    } else {
        waiting = !N.lost && !N.hostBackRead;
    }
    if (waiting && N.patience == 0)
        fault("the link's own timeout with %d still to come back", waiting);
    if (!waiting && N.patience != 0)
        fault("the race's timeout with every console back");
}

// The race run from car select and over (the key "RB"): the frontend
// unlaunched at its start, the lobby left on the stack's top by
// gameflow's raceReturn; netrace_end at its end; the frontend launched
// again after it, on the lobby.
static void raceAndBack(void)
{
    int i;

    if (!g_gf.screen || strcmp(g_gf.screen->name, LOBBY_NEXT_SCREEN)) {
        fault("the race from %s", g_gf.screen ? g_gf.screen->name : "-");
        return;
    }
    N.racing = 1;
    bgf_unlaunch_frontend_menus(&g_gf);
    N.racing = 0;
    // netrace_end: the race's timeout, and the lobby told.
    N.patience = RACE_PATIENCE;
    lobby_back_next();
    N.returned     = 1;
    N.returnFrame  = g_frame;
    N.raceStarts   = 0;
    N.onCpu        = 0;
    N.joinerBacks  = 0;
    N.hostBackRead = 0;
    N.junkRead     = 0;
    N.startQueued  = N.startRead = 0;
    for (i = 0; i < MAX_CLIENTS; i++) {
        N.raced[i] = N.backsTo[i] = N.backRead[i] = N.junkFrom[i] = 0;
        N.starts[i] = 0;
    }
    for (i = 0; i < N.numPeers; i++)
        if (N.alive[i]) N.raced[N.order[i]] = 1;
    bgf_launch_frontend_menus(&g_gf);
    if (!onLobby()) {
        fault("back from the race on %s",
              g_gf.screen ? g_gf.screen->name : "-");
        return;
    }
    if (N.network && N.host) {
        if (!N.open) fault("back from the race, the network closed");
        for (i = 0; i < N.numPeers; i++)
            if (N.alive[i] && N.backsTo[N.order[i]] != 1)
                fault("back said to %d %d times", i,
                      N.backsTo[N.order[i]]);
    }
    if (N.network && !N.host && !N.lost && N.joinerBacks != 1)
        fault("a joiner back from the race said so %d times", N.joinerBacks);
}

static const char* wRaceReturn(void* user)
{
    (void)user;
    return N.racing ? LOBBY_SCREEN_NAME : NULL;
}

// The screen just entered: what leaving the lobby for it must have done.
static void checkEntered(const char* name)
{
    int i, alive = 0, place = 0;

    if (!strcmp(name, "Prev")) {
        if (N.up) fault("back to Prev with the link up");
        return;
    }
    if (strcmp(name, LOBBY_NEXT_SCREEN)) return;
    if (!N.up || !N.network) fault("on to car select with the link down");
    if (g_gf.stack.index != 2 || strcmp(g_gf.stack.names[0], "Prev")
        || strcmp(g_gf.stack.names[1], LOBBY_SCREEN_NAME))
        fault("car select over %d screens, the last %s", g_gf.stack.index,
              g_gf.stack.index ? g_gf.stack.names[g_gf.stack.index - 1]
                               : "-");
    if (N.raceStarts != 1)
        fault("on to car select with %d starts told", N.raceStarts);
    if (!N.host) {
        if (!N.startRead)
            fault("a joiner on to car select with no start read");
        return;
    }
    if (N.open) fault("on to car select with the network open");
    for (i = 0; i < N.numPeers; i++) alive += N.alive[i] != 0;
    for (i = 0; i < N.numPeers; i++) {
        if (!N.alive[i]) continue;
        place++;
        if (N.starts[i] != 1)
            fault("client %d sent %d starts", i, N.starts[i]);
        else if (N.startMsg[i][0] != alive + 1 || N.startMsg[i][1] != place)
            fault("client %d told place %d of %d", i, N.startMsg[i][1],
                  N.startMsg[i][0]);
        else if (N.startMsg[i][2] != HOST_GAME_TYPE
                 || N.startMsg[i][3] != N.cops)
            fault("client %d told game type %d, cops %d", i,
                  N.startMsg[i][2], N.startMsg[i][3]);
    }
}

// The lobby's start, as netrace_begin hears it: the host's CPU racers as
// its list showed them, none on a joiner.
static void wStart(const LobbyRace* race)
{
    int want     = N.host && cpuWanted() > 0 ? cpuWanted() : 0;
    int gameType = N.host || !S->shortStart ? HOST_GAME_TYPE : -1;
    int copsOn   = N.host ? N.cops : !S->shortStart;

    printf("started, place %d of %d, %d CPU racers, game type %d, cops %d\n",
           race->place, race->consoles, race->cpu, race->gameType,
           race->copsOn);
    N.raceStarts++;
    if (race->cpu != want)
        fault("started with %d CPU racers, not %d", race->cpu, want);
    if (race->gameType != gameType || race->copsOn != copsOn)
        fault("started with game type %d, cops %d", race->gameType,
              race->copsOn);
    if (N.host && (g_gf.copsOn != 0) != N.cops)
        fault("the flow's cops %d, told %d", g_gf.copsOn, N.cops);
}

// The setup as the lobby tells it, and the flow's hooks it calls: the
// cops, and the game type the setup left in Fred.
static void wSetup(int on)
{
    char line[32];
    snprintf(line, sizeof line, "flow: setup %d", on);
    wLog(line);
    N.setupOn = on;
}

static void wPolice(void* user, int copsOn)
{
    char line[32];
    (void)user;
    snprintf(line, sizeof line, "flow: police %d", copsOn);
    wLog(line);
    N.cops = copsOn != 0;
}

static int wGameType(void* user)
{
    (void)user;
    return HOST_GAME_TYPE;
}

static int wCpuWish(void)
{
    printf("cpu wish %d\n", S->cpuWish);
    return S->cpuWish;
}

// --------------------------------------------------------------- inputs

// The sound a press on popup `p` must make, BSND_NONE for none.
static int pressSound(const BPopup* p, int ev)
{
    if (!p) return -1;   // no popup: not the lobby's to say
    switch (ev) {
        case BJOY_MENU_SELECT:
            return p->cfg.numButtons ? BSND_MENU_SELECT : BSND_NONE;
        case BJOY_MENU_BACK:
            return BSND_MENU_CANCEL;
        case BJOY_SCROLL_LEFT:
            return p->cfg.numButtons >= 2 ? BSND_MENU_LEFT : BSND_NONE;
        case BJOY_SCROLL_RIGHT:
            return p->cfg.numButtons >= 2 ? BSND_MENU_RIGHT : BSND_NONE;
        default:
            return -1;
    }
}

static void press(const char* key)
{
    const BPopup* p;
    int           n, ev = 0, want, logBefore = g_numLog, idle;

    printf("press %s\n", key);
    g_pressThisFrame = 1;
    if (!strcmp(key, "H")) {
        // Host, and through the mode and the setup if they come; never
        // the mode with the wireless off.
        int off = radioIsOff();
        press("A");
        p = upPopup(&n);
        if (onLobby() && p && p->cfg.message
            && !strcmp(p->cfg.message, text(PORTLANG_HOST_MODE))) {
            if (off) fault("the mode asked with the wireless off");
            press("A");
        }
        if (onSetup()) press("S");
        return;
    }
    if (!strcmp(key, "S") || !strcmp(key, "SB") || !strcmp(key, "SS")) {
        // A setup screen's select, which pushes the lobby again (as the
        // Challenge's exit and the race setups' select do), its BACK, and
        // the Challenge's Setup.
        if (!onSetup()) {
            fault("press %s off the setup", key);
            return;
        }
        if (!strcmp(key, "S"))
            bgf_change_to_screen(&g_gf, LOBBY_SCREEN_NAME, 1);
        else if (!strcmp(key, "SB"))
            bgf_move_back_screen(&g_gf, 1);
        else
            bgf_change_to_screen(&g_gf, SINGLE_RACE_SETUP, 1);
        return;
    }
    if (!strcmp(key, "CB")) {
        // B on car select, which goes back a screen.
        if (g_gf.screen && !strcmp(g_gf.screen->name, LOBBY_NEXT_SCREEN))
            bgf_move_back_screen(&g_gf, 1);
        return;
    }
    if (!strcmp(key, "RB")) {
        raceAndBack();
        return;
    }
    if (!strcmp(key, "X")) {
        // The frontend going elsewhere, not through the lobby's popups.
        bgf_change_to_screen(&g_gf, "Prev", 0);
        return;
    }
    if (!strcmp(key, "N")) {
        // The race's setup lost the host (netrace.c), for the lobby's
        // return.
        lobby_notice_next(PORTLANG_LINK_LOST, "hp2host");
        return;
    }
    if (!strcmp(key, "A")) ev = BJOY_MENU_SELECT;
    else if (!strcmp(key, "B")) ev = BJOY_MENU_BACK;
    else if (!strcmp(key, "L")) ev = BJOY_SCROLL_LEFT;
    else if (!strcmp(key, "R")) ev = BJOY_SCROLL_RIGHT;
    p = upPopup(&n);
    want = pressSound(p, ev);
    idle = ev == BJOY_MENU_SELECT && p && p->cfg.numButtons == 0;
    N.nextAsked = ev == BJOY_MENU_SELECT && p && p->cfg.numButtons == 2
               && p->cfg.button[p->current % 2] == PORTLANG_NEXT;
    // A on CPU Racers: one more, none past as many as fit, and nothing if
    // the room has just filled.
    if (ev == BJOY_MENU_SELECT && p && N.host && p->cfg.numButtons > 0
        && p->cfg.button[p->current % p->cfg.numButtons]
           == PORTLANG_CPU_RACERS
        && cpuWanted() >= 0) {
        N.want  = cpuWanted() < room() ? cpuWanted() + 1 : 0;
        N.onCpu = 1;
    }
    g_numSounds = 0;
    if (!bpopup_joy(&g_gf, 0, ev, 1) && ev == BJOY_MENU_BACK)
        bgf_back_button(&g_gf, 0);
    // A move between the host's two buttons.
    if ((ev == BJOY_SCROLL_LEFT || ev == BJOY_SCROLL_RIGHT) && N.host) {
        const BPopup* q = upPopup(&n);
        if (q && q->cfg.numButtons == 2)
            N.onCpu = q->cfg.button[q->current % 2] == PORTLANG_CPU_RACERS;
    }
    if (want == BSND_NONE && g_numSounds)
        fault("press %s: sound %d, none wanted", key, g_sounds[0]);
    else if (want > 0 && (g_numSounds != 1 || g_sounds[0] != want))
        fault("press %s: %d sounds, the first %d, not one %d", key,
              g_numSounds, g_numSounds ? g_sounds[0] : 0, want);
    if (idle && g_numLog != logBefore)
        fault("A on a popup with no buttons said \"%s\"", g_log[logBefore]);
}

// --------------------------------------------------------------- a run

static void runScenario(const Scenario* sc)
{
    BGameFlowHooks hooks;
    int            f, e, k;

    S         = sc;
    g_faults  = 0;
    g_numLog  = 0;
    g_frame   = 0;
    g_entered = NULL;
    memset(&N, 0, sizeof N);
    memset(&g_last, 0, sizeof g_last);
    N.joined = -1;
    printf("scenario %s\n", sc->name);

    memset(&hooks, 0, sizeof hooks);
    hooks.trace     = wTrace;
    hooks.sound     = wSound;
    hooks.setPolice = wPolice;
    hooks.gameType  = wGameType;
    hooks.raceReturn = wRaceReturn;
    bgf_init(&g_gf, kStates, BGF_NUM_STATES, kScreens,
             (int)(sizeof kScreens / sizeof kScreens[0]), NULL, 0, &hooks);
    g_gf.currLanguage = sc->language;
    lobby_init(&kNet, wLog);
    lobby_on_start(wStart);
    lobby_on_setup(wSetup);
    if (sc->cpuFn) lobby_cpu_wish(wCpuWish);

    bgf_change_to_screen(&g_gf, "Prev", 0);
    bgf_change_to_screen(&g_gf, LOBBY_SCREEN_NAME, 1);
    checkFrame();

    for (f = 0; f < sc->frames; f++) {
        g_frame          = f;
        g_soundThisFrame = 0;
        g_pressThisFrame = 0;
        N.nextAsked      = 0;
        g_entered        = NULL;
        g_summons        = 0;
        fakeStep();
        for (k = 0; k < MAX_INPUTS; k++)
            if (sc->input[k].key && sc->input[k].frame == f)
                press(sc->input[k].key);
        N.nextAsked = 0;
        if (g_pressThisFrame) {
            // As the presses left it: a popup for what is so now, not what
            // the next tick puts right. A search begun waits for the tick.
            int began = N.searchBegan;
            N.searchBegan = 0;
            if (g_entered) checkEntered(g_entered);
            g_entered = NULL;
            checkFrame();
            N.searchBegan = began;
        }
        bgf_frame(&g_gf, SIXTIETH);
        if (g_entered) checkEntered(g_entered);
        checkFrame();
        checkAgain();
        checkPatience();
        if (onLobby() && radioIsOff() && N.up)
            fault("the lobby's link up with the wireless off");
    }

    printf("final %s link %d\n", g_gf.screen ? g_gf.screen->name : "-",
           N.up);
    if (!g_gf.screen || strcmp(g_gf.screen->name, sc->endScreen))
        fault("ends on %s, not %s", g_gf.screen ? g_gf.screen->name : "-",
              sc->endScreen);
    if (N.up != sc->endLink)
        fault("ends with the link %s", N.up ? "up" : "down");
    for (e = 0, k = 0; e < MAX_EXPECT && sc->expect[e]; e++) {
        while (k < g_numLog && strcmp(g_log[k], sc->expect[e])) k++;
        if (k == g_numLog) {
            fault("never said \"%s\" (in order)", sc->expect[e]);
            break;
        }
        k++;
    }
    printf("faults %d\n", g_faults);
}

int main(int argc, char** argv)
{
    int total = 0, a, i;

    if (argc < 2) {
        for (i = 0; i < NUM_SCENARIOS; i++) {
            runScenario(&kScenarios[i]);
            total += g_faults;
        }
    } else {
        for (a = 1; a < argc; a++) {
            int found = 0;
            for (i = 0; i < NUM_SCENARIOS; i++) {
                if (strcmp(kScenarios[i].name, argv[a])) continue;
                runScenario(&kScenarios[i]);
                total += g_faults;
                found = 1;
            }
            if (!found) {
                fprintf(stderr, "unknown scenario: %s\n", argv[a]);
                return 2;
            }
        }
    }
    printf("total faults %d\n", total);
    return 0;
}
