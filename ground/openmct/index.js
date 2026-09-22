import installYamcsPlugins from '../src/openmct-yamcs.js';

const config = {
    yamcsDictionaryEndpoint: "http://localhost:9000/yamcs-proxy/",
    yamcsHistoricalEndpoint: "http://localhost:9000/yamcs-proxy/",
    yamcsWebsocketEndpoint: "ws://localhost:9000/yamcs-proxy-ws/",
    yamcsUserEndpoint: "http://localhost:9000/yamcs-proxy/api/user/",
    yamcsInstance: "fprime-project",
    yamcsProcessor: "realtime",
    yamcsFolder: "fprime-project",
    throttleRate: 1000,
    // Batch size is specified in characers as there is no performant way of calculating true
    // memory usage of a string buffer in real-time.
    // String characters can be 8 or 16 bits in JavaScript, depending on the code page used.
    // Thus 500,000 characters requires up to 16MB of memory (1,000,000 * 16).
    maxBufferSize: 1000000,
    planExecutionStatusParameter: '/fprime-project/PlanExecutionStatus'
};
const STATUS_STYLES = {
    NO_STATUS: {
        iconClass: "icon-question-mark",
        iconClassPoll: "icon-status-poll-question-mark"
    },
    GO: {
        iconClass: "icon-check",
        iconClassPoll: "icon-status-poll-question-mark",
        statusClass: "s-status-ok",
        statusBgColor: "#33cc33",
        statusFgColor: "#000"
    },
    MAYBE: {
        iconClass: "icon-alert-triangle",
        iconClassPoll: "icon-status-poll-question-mark",
        statusClass: "s-status-warning",
        statusBgColor: "#ffb66c",
        statusFgColor: "#000"
    },
    NO_GO: {
        iconClass: "icon-circle-slash",
        iconClassPoll: "icon-status-poll-question-mark",
        statusClass: "s-status-error",
        statusBgColor: "#9900cc",
        statusFgColor: "#fff"
    }
};
const openmct = window.openmct;

(() => {
    const POLL_INTERVAL = 100; // ms
    const MAX_POLL_TIME = 10000; // 10 seconds
    const COMPOSITION_RETRY_DELAY = 250; // ms
    const MAX_COMPOSITION_RETRIES = 20; // 5 seconds total with 250ms intervals
    const ONE_SECOND = 1000;
    const ONE_MINUTE = ONE_SECOND * 60;
    const THIRTY_MINUTES = ONE_MINUTE * 30;

    openmct.setAssetPath("/node_modules/openmct/dist");

    installDefaultPlugins();
    openmct.install(installYamcsPlugins(config));
    openmct.install(
        openmct.plugins.OperatorStatus({ statusStyles: STATUS_STYLES })
    );

    document.addEventListener("DOMContentLoaded", function () {
        openmct.start();
    });
    openmct.install(
        openmct.plugins.Conductor({
            menuOptions: [
                {
                    name: "Realtime",
                    timeSystem: "utc",
                    clock: "local",
                    clockOffsets: {
                        start: -THIRTY_MINUTES,
                        end: 0
                    }
                },
                {
                    name: "Fixed",
                    timeSystem: "utc",
                    bounds: {
                        start: Date.now() - THIRTY_MINUTES,
                        end: 0
                    }
                }
            ]
        })
    );

    function installDefaultPlugins() {
        openmct.install(openmct.plugins.LocalStorage());
        openmct.install(openmct.plugins.Espresso());
        openmct.install(openmct.plugins.MyItems());
        openmct.install(openmct.plugins.example.Generator());
        openmct.install(openmct.plugins.example.ExampleImagery());
        openmct.install(openmct.plugins.UTCTimeSystem());
        openmct.install(openmct.plugins.TelemetryMean());

        openmct.install(
            openmct.plugins.DisplayLayout({
                showAsView: ["summary-widget", "example.imagery", "yamcs.image"]
            })
        );
        openmct.install(openmct.plugins.SummaryWidget());
        openmct.install(openmct.plugins.Notebook());
        openmct.install(openmct.plugins.LADTable());
        openmct.install(
            openmct.plugins.ClearData([
                "table",
                "telemetry.plot.overlay",
                "telemetry.plot.stacked"
            ])
        );

        openmct.install(openmct.plugins.FaultManagement());
        if (openmct.plugins.BarChart) openmct.install(openmct.plugins.BarChart());
        openmct.install(openmct.plugins.PlanLayout({ creatable: true }));
        const timelinePlugin = openmct.plugins.Timeline();
        openmct.install(timelinePlugin);
        if (openmct.plugins.EventTimestripPlugin) openmct.install(openmct.plugins.EventTimestripPlugin(timelinePlugin.extendedLinesBus));

        // Land on the Doom frame product (imagery view from Yamcs) instead of the plugin's example layout, whose
        // demo objects (instance "myproject") do not exist here and raise "Error requesting telemetry data".
        openmct.on('start', () => {
            // the router lands on My Items a moment after start; only redirect if the user did not ask for something else
            setTimeout(() => {
                const h = window.location.hash;
                if (!h || h === '#/' || h.startsWith('#/browse/mine')) {
                    openmct.router.navigate('#/browse/taxonomy:spacecraft/taxonomy:~DoomGround/taxonomy:~DoomGround~DoomFrame'
                        + '?tc.mode=local&tc.startDelta=1800000&tc.endDelta=0&tc.timeSystem=utc&view=example.imagery');
                }
            }, 1000);
        });
    }
})();
