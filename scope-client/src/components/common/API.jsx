class API {
	constructor() {
		this.GBC = require("grpc-bus-websocket-client");
		this.GBCConnection = new this.GBC("ws://localhost:8081/", 'src/proto/s.proto', { scope: { Main: 'localhost:50052' } }).connect();
		this.activeLoom = null;
		this.features = {
			'gene': {
				0: {type: 'gene', value: ''},
				1: {type: 'gene', value: ''},
				2: {type: 'gene', value: ''}
			}, 
			'regulon': {
				0: {type: 'regulon', value: ''},
				1: {type: 'regulon', value: ''},
				2: {type: 'regulon', value: ''}
			}, 
		};
		this.featureChangeListeners = [];
		this.activeLoomChangeListeners = [];
		this.hasLogTranform = true;
		this.hasCpmTranform = true;
	}

	getConnection() {
		return this.GBCConnection;
	}


	getActiveLoom() {
		return this.activeLoom;
	}

	setActiveLoom(loom) {
		this.activeLoom = loom;
		this.activeLoomChangeListeners.forEach((listener) => {
			listener(this.activeLoom);
		})
	}

	onActiveLoomChange(listener) {
		this.activeLoomChangeListeners.push(listener);
	}


	getActiveFeatures(type) {
		return this.features[type];
	}

	setActiveFeature(featureId, featureType, featureValue) {
		this.features[featureType][featureId] = { type: featureType, value: featureValue }
		this.featureChangeListeners.forEach((listener) => {
			listener(this.features[featureType]);
		})
	}

	onActiveFeaturesChange(listener) {
		this.featureChangeListeners.push(listener);
	}



}

export let BackendAPI = new API();