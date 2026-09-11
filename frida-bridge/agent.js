// Frida agent injected into the target app for a dynamic-trace run.
// Purely observational: every hook logs, none of them alter behavior or
// bypass anything (e.g. SecTrustEvaluate is watched, never faked).
//
// This file is a build INPUT, not what actually gets loaded — Frida 17+
// dropped ObjC as an ambient global, so it must be pulled in via the
// frida-objc-bridge npm package and bundled with frida-compile (see
// package.json's "build" script and README.md). runner.py loads the
// resulting agent-bundle.js.

import ObjC from "frida-objc-bridge";

const START = Date.now();

function emit(category, summary, detail) {
  send({
    category: category,
    summary: summary,
    detail: detail === undefined ? null : detail,
    ts_offset_ms: Date.now() - START,
  });
}

const MAX_BODY_BYTES = 8192;

// NSData's bytes are read-only here — never touched via HTTPBodyStream,
// which would consume the stream and break the real request.
function describeNsData(data) {
  if (!data || data.isNull()) {
    return { body_length: 0, body: null };
  }

  const len = data.length().valueOf();
  if (len === 0) {
    return { body_length: 0, body: null };
  }

  try {
    const ptr = data.bytes();
    const readLen = Math.min(len, MAX_BODY_BYTES);
    const text = Memory.readUtf8String(ptr, readLen);
    return {
      body_length: len,
      body: text,
      body_truncated: len > MAX_BODY_BYTES,
    };
  } catch (e) {
    return { body_length: len, body: null, body_note: "binary (not valid UTF-8, possibly compressed — check Content-Encoding)" };
  }
}

function describeHttpBody(request) {
  const stream = request.HTTPBodyStream ? request.HTTPBodyStream() : null;
  if (stream && !stream.isNull()) {
    return { body_length: null, body: null, body_note: "sent via HTTPBodyStream (not read, to avoid consuming it)" };
  }
  return describeNsData(request.HTTPBody ? request.HTTPBody() : null);
}

function describeObjcArg(value, typeChar) {
  try {
    if (value.isNull()) return null;
    if (typeChar === "@") {
      const obj = new ObjC.Object(value);
      return obj.toString();
    }
    if (typeChar === ":" || typeChar === "#") {
      return value.toString();
    }
    return value.toString();
  } catch (e) {
    return "<unreadable>";
  }
}

function hookObjcClasses(classNames) {
  const hooked = [];
  const failed = [];
  classNames.forEach((className) => {
    const cls = ObjC.classes[className];
    if (!cls) {
      failed.push(className);
      return;
    }
    let methodNames;
    try {
      methodNames = cls.$ownMethods;
    } catch (e) {
      failed.push(className);
      return;
    }
    methodNames.forEach((methodName) => {
      try {
        const method = cls[methodName];
        const impl = method.implementation;
        const argTypes = method.argumentTypes || [];
        Interceptor.attach(impl, {
          onEnter(args) {
            const argDescs = [];
            for (let i = 2; i < argTypes.length; i++) {
              argDescs.push(describeObjcArg(args[i], argTypes[i]));
            }
            this._selDesc = className + " " + methodName;
            this._argDescs = argDescs;
          },
          onLeave(retval) {
            emit("objc_call", this._selDesc, {
              class: className,
              selector: methodName,
              args: this._argDescs,
            });
          },
        });
        hooked.push(className + methodName);
      } catch (e) {
        failed.push(className + methodName);
      }
    });
  });
  return { hooked: hooked.length, failed: failed };
}

function hookNetwork() {
  try {
    const NSURLSessionTask = ObjC.classes.NSURLSessionTask;
    if (NSURLSessionTask) {
      const resume = NSURLSessionTask["- resume"];
      if (resume) {
        Interceptor.attach(resume.implementation, {
          onEnter(args) {
            try {
              const task = new ObjC.Object(args[0]);
              const request = task.currentRequest();
              if (request && !request.isNull()) {
                const url = request.URL() && !request.URL().isNull() ? request.URL().absoluteString().toString() : null;
                const method = request.HTTPMethod() && !request.HTTPMethod().isNull() ? request.HTTPMethod().toString() : null;
                const headers = request.allHTTPHeaderFields() && !request.allHTTPHeaderFields().isNull()
                  ? request.allHTTPHeaderFields().toString()
                  : null;
                emit("network", (method || "?") + " " + (url || "?"), Object.assign(
                  { url: url, method: method, headers: headers },
                  describeHttpBody(request)
                ));
              }
            } catch (e) {
              /* best-effort */
            }
          },
        });
      }
    }
  } catch (e) {
    emit("error", "network hook setup failed", { error: String(e) });
  }

  try {
    const NSURLConnection = ObjC.classes.NSURLConnection;
    if (NSURLConnection) {
      const sync = NSURLConnection["+ sendSynchronousRequest:returningResponse:error:"];
      if (sync) {
        Interceptor.attach(sync.implementation, {
          onEnter(args) {
            try {
              const request = new ObjC.Object(args[2]);
              const url = request.URL() && !request.URL().isNull() ? request.URL().absoluteString().toString() : null;
              const method = request.HTTPMethod() && !request.HTTPMethod().isNull() ? request.HTTPMethod().toString() : null;
              emit("network", (method || "?") + " " + (url || "?") + " (sync)", Object.assign(
                { url: url, method: method },
                describeHttpBody(request)
              ));
            } catch (e) {
              /* best-effort */
            }
          },
        });
      }
    }
  } catch (e) {
    emit("error", "NSURLConnection hook setup failed", { error: String(e) });
  }

  // uploadTaskWithRequest:fromData: passes the body as a separate argument
  // that's never attached to the request object — resume() alone can't see
  // it, so this is the only way to capture bodies sent this way (a common
  // pattern for analytics/telemetry SDKs, e.g. Firebase/GA beacons).
  try {
    const NSURLSession = ObjC.classes.NSURLSession;
    if (NSURLSession) {
      ["- uploadTaskWithRequest:fromData:", "- uploadTaskWithRequest:fromData:completionHandler:"].forEach((sel) => {
        const method = NSURLSession[sel];
        if (!method) return;
        Interceptor.attach(method.implementation, {
          onEnter(args) {
            try {
              const request = new ObjC.Object(args[2]);
              const data = new ObjC.Object(args[3]);
              const url = request.URL() && !request.URL().isNull() ? request.URL().absoluteString().toString() : null;
              const httpMethod = request.HTTPMethod() && !request.HTTPMethod().isNull() ? request.HTTPMethod().toString() : "POST";
              emit("network", httpMethod + " " + (url || "?") + " (upload)", Object.assign(
                { url: url, method: httpMethod },
                describeNsData(data)
              ));
            } catch (e) {
              /* best-effort */
            }
          },
        });
      });
    }
  } catch (e) {
    emit("error", "uploadTask hook setup failed", { error: String(e) });
  }
}

function hookCryptoAndKeychain() {
  const targets = [
    { name: "SecItemAdd", category: "keychain" },
    { name: "SecItemCopyMatching", category: "keychain" },
    { name: "SecItemUpdate", category: "keychain" },
    { name: "SecItemDelete", category: "keychain" },
    { name: "SecTrustEvaluate", category: "crypto" },
    { name: "SecTrustEvaluateWithError", category: "crypto" },
    { name: "CCCryptorCreate", category: "crypto" },
    { name: "CCCrypt", category: "crypto" },
  ];
  targets.forEach(({ name, category }) => {
    try {
      const addr = Module.findGlobalExportByName(name);
      if (!addr) return;
      Interceptor.attach(addr, {
        onEnter(args) {
          this._name = name;
          this._category = category;
        },
        onLeave(retval) {
          emit(this._category, this._name + "()", {
            function: this._name,
            retval: retval.toInt32(),
          });
        },
      });
    } catch (e) {
      emit("error", "hook failed: " + name, { error: String(e) });
    }
  });
}

rpc.exports = {
  configure(config) {
    if (!ObjC.available) {
      emit("error", "ObjC runtime not available in this process", null);
      return { ok: false };
    }

    emit("lifecycle", "agent configured", { config: config });

    let objcResult = { hooked: 0, failed: [] };
    if (config.classes && config.classes.length > 0) {
      objcResult = hookObjcClasses(config.classes);
    }
    if (config.trace_network) {
      hookNetwork();
    }
    if (config.trace_crypto) {
      hookCryptoAndKeychain();
    }

    emit("lifecycle", "hooks installed", {
      objc_hooked: objcResult.hooked,
      objc_failed: objcResult.failed,
      network: !!config.trace_network,
      crypto: !!config.trace_crypto,
    });

    return { ok: true, objc: objcResult };
  },
};
