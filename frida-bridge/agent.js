// Frida agent injected into the target app for a dynamic-trace run.
// Purely observational: every hook logs, none of them alter behavior or
// bypass anything (e.g. SecTrustEvaluate is watched, never faked).

const START = Date.now();

function emit(category, summary, detail) {
  send({
    category: category,
    summary: summary,
    detail: detail === undefined ? null : detail,
    ts_offset_ms: Date.now() - START,
  });
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
                const body = request.HTTPBody();
                const bodyLen = body && !body.isNull() ? body.length().valueOf() : 0;
                emit("network", (method || "?") + " " + (url || "?"), {
                  url: url,
                  method: method,
                  headers: headers,
                  body_length: bodyLen,
                });
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
              emit("network", (method || "?") + " " + (url || "?") + " (sync)", { url: url, method: method });
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
      const addr = Module.findExportByName(null, name);
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
